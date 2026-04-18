"""Evidence agent -- ClaimReview lookup + domain-source evidence gathering.

Uses LangChain v1's ``state_schema`` + ``Command(update=...)`` pattern.
Tools write structured results directly into ``EvidenceAgentState``
(list-append fields use an ``operator.add`` reducer; ``best_confidence``
uses read-modify-write for max semantics). A free function
``evidence_output_from_state`` projects the final state into the
existing :class:`EvidenceOutput` TypedDict so the LLM never re-serializes
structured payloads.

Pipeline integration (PipelineContext, observation publishing,
PipelineState ↔ EvidenceInput translation) lives in the pipeline node
wrapper, not here.
"""

from __future__ import annotations

import json
import logging
import operator
import os
from typing import Annotated, Any

from langchain.agents import AgentState, create_agent
from langchain.tools import ToolRuntime
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from typing_extensions import NotRequired

from swarm_reasoning.agents.evidence.models import EvidenceInput, EvidenceOutput
from swarm_reasoning.temporal.errors import MissingApiKeyError

logger = logging.getLogger(__name__)

AGENT_NAME = "evidence"
AGENT_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You are an evidence-gathering agent in a fact-checking pipeline. "
    "Gather evidence for or against the given claim using your tools.\n\n"
    "Workflow:\n"
    "1. Search for existing fact-checks with search_factchecks\n"
    "2. Look up domain-authoritative sources with lookup_domain_sources\n"
    "3. Fetch content from the top source with fetch_source_content\n"
    "4. Score the fetched content with score_evidence\n\n"
    "Always start with the fact-check lookup. Then proceed to domain "
    "sources. Try up to 3 domain source URLs if the first returns an "
    "error. Stop after scoring evidence from one successful source.\n\n"
    "After completing the workflow, reply with a one-line confirmation. "
    "Do NOT attempt to echo tool outputs back as JSON -- the system "
    "captures tool results directly."
)


# ---------------------------------------------------------------------------
# Agent state schema
# ---------------------------------------------------------------------------


class EvidenceAgentState(AgentState):
    """State schema carrying evidence input fields and tool outputs.

    Input fields (``claim_text``, ``domain``, entity lists) are seeded
    by the caller and read by tools via ``runtime.state``. Output fields
    (``claimreview_matches``, ``domain_sources``, ``best_confidence``)
    are written by tools via ``Command(update=...)``; the list fields
    use an ``operator.add`` reducer so repeat calls append rather than
    replace.
    """

    # Input fields (seeded by caller)
    claim_text: NotRequired[str]
    domain: NotRequired[str]
    persons: NotRequired[list[str]]
    organizations: NotRequired[list[str]]
    dates: NotRequired[list[str]]
    locations: NotRequired[list[str]]
    statistics: NotRequired[list[str]]

    # Output fields (written by tools)
    claimreview_matches: NotRequired[Annotated[list[dict], operator.add]]
    domain_sources: NotRequired[Annotated[list[dict], operator.add]]
    best_confidence: NotRequired[float]


# ---------------------------------------------------------------------------
# State -> EvidenceOutput projection
# ---------------------------------------------------------------------------


def evidence_output_from_state(state: dict[str, Any]) -> EvidenceOutput:
    """Project captured evidence state into an :class:`EvidenceOutput`."""
    return EvidenceOutput(
        claimreview_matches=list(state.get("claimreview_matches") or []),
        domain_sources=list(state.get("domain_sources") or []),
        evidence_confidence=float(state.get("best_confidence") or 0.0),
    )


# ---------------------------------------------------------------------------
# User-message formatting (re-used by pipeline node + CLI)
# ---------------------------------------------------------------------------


def format_claim_message(evidence_input: EvidenceInput) -> str:
    """Render the user message that frames the gathering task for the LLM."""
    persons = ", ".join(evidence_input.get("persons", []) or [])
    organizations = ", ".join(evidence_input.get("organizations", []) or [])
    return (
        "Gather evidence for this claim:\n\n"
        f"Claim: {evidence_input.get('claim_text', '')}\n"
        f"Domain: {evidence_input.get('domain', 'OTHER')}\n"
        f"Persons: {persons}\n"
        f"Organizations: {organizations}"
    )


def initial_state_from_input(evidence_input: EvidenceInput) -> dict[str, Any]:
    """Build the initial ``EvidenceAgentState`` dict for an invocation.

    Seeds input fields on state so tools can read them via
    ``runtime.state`` and attaches the user-facing claim message.
    """
    return {
        "messages": [("user", format_claim_message(evidence_input))],
        "claim_text": evidence_input.get("claim_text", ""),
        "domain": evidence_input.get("domain", "OTHER"),
        "persons": list(evidence_input.get("persons", []) or []),
        "organizations": list(evidence_input.get("organizations", []) or []),
        "dates": list(evidence_input.get("dates", []) or []),
        "locations": list(evidence_input.get("locations", []) or []),
        "statistics": list(evidence_input.get("statistics", []) or []),
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


@tool
async def search_factchecks(reason: str, runtime: ToolRuntime) -> Command:
    """Search Google Fact Check Tools API for existing reviews of the claim.

    Args:
        reason: Short rationale for issuing the search; ignored by the tool.
    """
    from swarm_reasoning.agents.evidence.tools import (
        search_factchecks as search_mod,
    )
    from swarm_reasoning.agents.messaging import (
        share_heartbeat,
        share_progress,
    )

    del reason
    state = runtime.state
    share_progress("Searching fact-check databases...")
    share_heartbeat(AGENT_NAME)
    result = await search_mod.search_factchecks(
        claim=state.get("claim_text", ""),
        persons=state.get("persons"),
        organizations=state.get("organizations"),
    )
    share_heartbeat(AGENT_NAME)

    if result.error:
        content = f"Error: {result.error}"
        update: dict[str, Any] = {}
    elif not result.matched:
        content = "No matching fact-checks found."
        update = {}
    else:
        match = {
            "source": result.source,
            "rating": result.rating,
            "url": result.url,
            "score": round(result.score, 2),
        }
        update = {"claimreview_matches": [match]}
        content = (
            f"Match found (score: {result.score:.2f}):\n"
            f"  Rating: {result.rating}\n"
            f"  Source: {result.source}\n"
            f"  URL: {result.url}"
        )

    update["messages"] = [ToolMessage(content=content, tool_call_id=runtime.tool_call_id)]
    return Command(update=update)


@tool
def lookup_domain_sources(reason: str, runtime: ToolRuntime) -> str:
    """Look up authoritative sources for the claim's domain.

    Returns a JSON list of sources with name and pre-formatted URL.

    Args:
        reason: Short rationale for the lookup; ignored by the tool.
    """
    from swarm_reasoning.agents.evidence.tools import lookup_domain_sources as lookup_mod
    from swarm_reasoning.agents.messaging import share_progress

    del reason
    state = runtime.state
    share_progress("Looking up domain-authoritative sources...")
    domain = state.get("domain", "OTHER")
    sources = lookup_mod.lookup_domain_sources(domain)
    search_query = lookup_mod.derive_search_query(
        state.get("claim_text", ""),
        state.get("persons"),
        state.get("organizations"),
        state.get("statistics"),
        state.get("dates"),
    )
    return json.dumps(
        [
            {
                "name": s.name,
                "url": lookup_mod.format_source_url(s.url_template, search_query),
            }
            for s in sources
        ]
    )


@tool
async def fetch_source_content(url: str) -> str:
    """Fetch text content from a source URL.

    Args:
        url: The full URL to fetch (use URLs from lookup_domain_sources).
    """
    from swarm_reasoning.agents.evidence.tools import (
        fetch_source_content as fetch_mod,
    )
    from swarm_reasoning.agents.messaging import (
        share_heartbeat,
        share_progress,
    )

    share_progress(f"Fetching source: {url}")
    share_heartbeat(AGENT_NAME)
    result = await fetch_mod.fetch_source_content(url)
    share_heartbeat(AGENT_NAME)
    if result.error:
        return f"Error fetching {url}: {result.error}"
    return result.content


@tool
def score_evidence(
    content: str, source_name: str, source_url: str, runtime: ToolRuntime
) -> Command:
    """Score how well fetched content aligns with the claim.

    Args:
        content: The fetched source content to evaluate.
        source_name: Name of the source (e.g. CDC, WHO).
        source_url: URL the content was fetched from.
    """
    from swarm_reasoning.agents.evidence.tools import score_evidence as score_mod
    from swarm_reasoning.agents.messaging import share_progress

    state = runtime.state
    share_progress(f"Scoring evidence from {source_name}...")
    alignment_result = score_mod.score_claim_alignment(content, state.get("claim_text", ""))
    confidence = score_mod.compute_evidence_confidence(alignment_result.alignment)

    entry = {
        "name": source_name,
        "url": source_url,
        "alignment": alignment_result.alignment.value,
        "confidence": confidence,
    }
    update: dict[str, Any] = {"domain_sources": [entry]}
    prev_best = float(state.get("best_confidence") or 0.0)
    if confidence > prev_best:
        update["best_confidence"] = confidence

    text = (
        f"Alignment: {alignment_result.alignment.value} "
        f"({alignment_result.description})\n"
        f"Confidence: {confidence:.2f}"
    )
    update["messages"] = [ToolMessage(content=text, tool_call_id=runtime.tool_call_id)]
    return Command(update=update)


_TOOLS: list[Any] = [
    search_factchecks,
    lookup_domain_sources,
    fetch_source_content,
    score_evidence,
]


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


def build_evidence_agent(model: ChatAnthropic | None = None) -> Any:
    """Build the evidence agent as a compiled LangGraph.

    Args:
        model: Optional ChatAnthropic instance for the orchestrator. If
            ``None``, one is created from the ``ANTHROPIC_API_KEY``
            environment variable.

    Returns:
        A compiled LangGraph whose state is ``EvidenceAgentState``. Invoke
        with an initial state built by ``initial_state_from_input(...)``
        and project the final state with ``evidence_output_from_state``.
    """
    if model is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError("ANTHROPIC_API_KEY is required for evidence agent")
        model = ChatAnthropic(
            model=AGENT_MODEL,
            max_tokens=1024,
            temperature=0,
            api_key=api_key,
        )

    return create_agent(
        model=model,
        tools=_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        state_schema=EvidenceAgentState,
        name=AGENT_NAME,
    )
