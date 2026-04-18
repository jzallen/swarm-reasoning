"""Evidence agent -- ClaimReview lookup + domain-source evidence gathering.

Implemented as a deterministic LangGraph ``StateGraph``: no LLM decides the
sequence, no tools, no system prompt. Each node wraps one pure function
from ``agents.evidence.tools``.

Topology::

    START -> search_factchecks -> lookup_domain_sources -> fetch_source_content
                                                             |  ^
                                                             |  | retry (<3)
                                                             v  |
                                                          score_evidence -> END
                                                             (or give_up -> END)

Pipeline integration (PipelineContext, observation publishing,
PipelineState <-> EvidenceInput translation) lives in the pipeline node
wrapper, not here.
"""

from __future__ import annotations

import logging
import operator
from typing import Annotated, Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import NotRequired, TypedDict

from swarm_reasoning.agents.evidence.models import EvidenceInput
from swarm_reasoning.agents.evidence.tools import (
    lookup_domain_sources as lookup_module,
)
from swarm_reasoning.agents.evidence.tools import (
    score_evidence as score_module,
)
from swarm_reasoning.agents.evidence.tools import (
    search_factchecks as search_module,
)
from swarm_reasoning.agents.messaging import share_heartbeat, share_progress
from swarm_reasoning.agents.web import (
    BeautifulSoupStrategy,
    FetchCache,
    FetchErr,
    FetchOk,
    RawTextStrategy,
    TrafilaturaStrategy,
    WebContentExtractor,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "evidence"

MAX_FETCH_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Agent state schema
# ---------------------------------------------------------------------------


class EvidenceAgentState(TypedDict, total=False):
    """State schema carrying evidence input fields, transient orchestration
    fields, and structured outputs.

    List outputs (``claimreview_matches``, ``domain_sources``) use an
    ``operator.add`` reducer so node writes append rather than replace.
    Transient orchestration fields are underscore-prefixed; they drive the
    fetch-retry loop and are not projected by the pipeline node wrapper.
    """

    # Input fields (seeded by caller)
    claim_text: NotRequired[str]
    domain: NotRequired[str]
    persons: NotRequired[list[str]]
    organizations: NotRequired[list[str]]
    dates: NotRequired[list[str]]
    locations: NotRequired[list[str]]
    statistics: NotRequired[list[str]]

    # Output fields
    claimreview_matches: NotRequired[Annotated[list[dict], operator.add]]
    domain_sources: NotRequired[Annotated[list[dict], operator.add]]
    best_confidence: NotRequired[float]

    # Transient orchestration fields (internal; not exposed externally)
    _candidate_sources: NotRequired[list[dict]]
    _fetched_content: NotRequired[str]
    _fetched_source_name: NotRequired[str]
    _fetched_source_url: NotRequired[str]
    _fetch_attempts: NotRequired[int]


def initial_state_from_input(evidence_input: EvidenceInput) -> dict[str, Any]:
    """Build the initial ``EvidenceAgentState`` dict for an invocation."""
    return {
        "claim_text": evidence_input.get("claim_text", ""),
        "domain": evidence_input.get("domain", "OTHER"),
        "persons": list(evidence_input.get("persons", []) or []),
        "organizations": list(evidence_input.get("organizations", []) or []),
        "dates": list(evidence_input.get("dates", []) or []),
        "locations": list(evidence_input.get("locations", []) or []),
        "statistics": list(evidence_input.get("statistics", []) or []),
    }


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


def build_evidence_agent() -> CompiledStateGraph:
    """Build the evidence agent as a compiled deterministic ``StateGraph``.

    Returns:
        Compiled ``StateGraph`` whose state is :class:`EvidenceAgentState`.
        Invoke with an initial state dict from :func:`initial_state_from_input`.
    """
    extractor = WebContentExtractor(
        strategies=[TrafilaturaStrategy(), BeautifulSoupStrategy(), RawTextStrategy()],
        cache=FetchCache(),
    )

    async def _search_factchecks_node(state: EvidenceAgentState) -> dict[str, Any]:
        share_progress("Searching fact-check databases...")
        share_heartbeat(AGENT_NAME)
        try:
            result = await search_module.search_factchecks(
                claim=state.get("claim_text", ""),
                persons=state.get("persons"),
                organizations=state.get("organizations"),
            )
        except Exception as exc:
            logger.warning("search_factchecks raised: %s", exc)
            return {}
        share_heartbeat(AGENT_NAME)

        if result.error or not result.matched:
            return {}
        return {
            "claimreview_matches": [
                {
                    "source": result.source,
                    "rating": result.rating,
                    "url": result.url,
                    "score": round(result.score, 2),
                }
            ]
        }

    def _lookup_domain_sources_node(state: EvidenceAgentState) -> dict[str, Any]:
        share_progress("Looking up domain-authoritative sources...")
        query = lookup_module.derive_search_query(
            state.get("claim_text", ""),
            state.get("persons"),
            state.get("organizations"),
            state.get("statistics"),
            state.get("dates"),
        )
        sources = lookup_module.lookup_domain_sources(state.get("domain", "OTHER"), query)
        return {
            "_candidate_sources": [{"name": s.name, "url": s.url} for s in sources.sources],
        }

    async def _fetch_source_content_node(state: EvidenceAgentState) -> dict[str, Any]:
        candidates = list(state.get("_candidate_sources") or [])
        attempts = int(state.get("_fetch_attempts") or 0)
        if not candidates:
            return {}

        candidate = candidates.pop(0)
        url = candidate["url"]
        share_progress(f"Fetching source: {url}")
        share_heartbeat(AGENT_NAME)
        result = await extractor.fetch(url)
        share_heartbeat(AGENT_NAME)

        update: dict[str, Any] = {
            "_candidate_sources": candidates,
            "_fetch_attempts": attempts + 1,
        }
        match result:
            case FetchOk(document=doc):
                update["_fetched_content"] = doc.text
                update["_fetched_source_name"] = candidate["name"]
                update["_fetched_source_url"] = url
            case FetchErr(reason=code):
                logger.info("fetch failed for %s: %s", url, code)
        return update

    def _fetch_outcome(state: EvidenceAgentState) -> Literal["score", "retry", "give_up"]:
        if state.get("_fetched_content"):
            return "score"
        if int(state.get("_fetch_attempts") or 0) >= MAX_FETCH_ATTEMPTS:
            return "give_up"
        if not state.get("_candidate_sources"):
            return "give_up"
        return "retry"

    def _score_evidence_node(state: EvidenceAgentState) -> dict[str, Any]:
        name = state.get("_fetched_source_name", "")
        url = state.get("_fetched_source_url", "")
        content = state.get("_fetched_content", "")
        share_progress(f"Scoring evidence from {name}...")
        alignment_result = score_module.score_claim_alignment(content, state.get("claim_text", ""))
        confidence = score_module.compute_evidence_confidence(alignment_result.alignment)

        entry = {
            "name": name,
            "url": url,
            "alignment": alignment_result.alignment.value,
            "confidence": confidence,
        }
        update: dict[str, Any] = {"domain_sources": [entry]}
        prev_best = float(state.get("best_confidence") or 0.0)
        if confidence > prev_best:
            update["best_confidence"] = confidence
        return update

    builder: StateGraph = StateGraph(EvidenceAgentState)
    builder.add_node("search_factchecks", _search_factchecks_node)
    builder.add_node("lookup_domain_sources", _lookup_domain_sources_node)
    builder.add_node("fetch_source_content", _fetch_source_content_node)
    builder.add_node("score_evidence", _score_evidence_node)

    builder.add_edge(START, "search_factchecks")
    builder.add_edge("search_factchecks", "lookup_domain_sources")
    builder.add_edge("lookup_domain_sources", "fetch_source_content")
    builder.add_conditional_edges(
        "fetch_source_content",
        _fetch_outcome,
        {
            "score": "score_evidence",
            "retry": "fetch_source_content",
            "give_up": END,
        },
    )
    builder.add_edge("score_evidence", END)
    return builder.compile()
