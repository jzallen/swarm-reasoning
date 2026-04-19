"""Evidence agent -- ClaimReview lookup + domain-source evidence gathering.

Built with LangGraph's Functional API (``@entrypoint`` + ``@task``). The
control flow is a straight-line deterministic pipeline:

    search_factchecks ─┐
                       ├─► score_sources ─► format_response ─► END
    lookup_sources ────┘   (LLM subagent)

``search_factchecks`` and ``lookup_sources`` run concurrently; the LLM
subagent in ``score_sources`` judges alignment on fetched content and
returns SUPPORTS / CONTRADICTS / PARTIAL / ABSENT. Temperature is 0.4 for
the judgment step -- enough creative latitude to recognize empty search
pages, login walls, and irrelevant content as ABSENT, rather than
rubber-stamping keyword overlap.

Pipeline integration (PipelineContext, observation publishing,
PipelineState <-> EvidenceInput translation) lives in the pipeline node
wrapper, not here.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from langchain.agents import AgentState, create_agent
from langchain.tools import ToolRuntime
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.func import entrypoint, task
from langgraph.types import Command
from typing_extensions import NotRequired

from swarm_reasoning.agents.evidence.models import EvidenceInput
from swarm_reasoning.agents.evidence.tasks import (
    format_response,
    lookup_sources,
    search_factcheck_matches,
)
from swarm_reasoning.agents.messaging import share_heartbeat, share_progress
from swarm_reasoning.agents.web import (
    BeautifulSoupStrategy,
    FetchCache,
    RawTextStrategy,
    TrafilaturaStrategy,
    WebContentExtractor,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "evidence"
SCORER_NAME = "evidence-scorer"
SCORER_MODEL = "claude-haiku-4-5-20251001"
SCORER_TEMPERATURE = 0.4
SCORER_MAX_TOKENS = 512

# ---------------------------------------------------------------------------
# Scorer system prompt
# ---------------------------------------------------------------------------

_SCORER_SYSTEM_PROMPT = """\
You judge whether a fetched source page actually supports a specific claim.

You will see: the claim, the source name, its URL, and an excerpt of the page
content. Decide ONE of:

  SUPPORTS     -- the content directly affirms the claim.
  CONTRADICTS  -- the content directly refutes or disproves the claim.
  PARTIAL      -- the content addresses the topic and is consistent with the
                  claim but does not fully confirm every element of it.
  ABSENT       -- the content does NOT bear on the claim. Use ABSENT when:
                    * the page is an empty search-results page
                      (e.g. "No results found", "0 results for ...")
                    * the page is a generic search form, login wall, or
                      error page
                    * the content is unrelated to the claim entirely
                    * the page only echoes your search query back without
                      returning any substantive article, dataset, or
                      release. A page that only contains query terms in
                      its chrome (breadcrumbs, search box label, "You
                      searched for: ...") is ABSENT.

Call the ``record_alignment`` tool exactly once with your verdict and a
1-2 sentence rationale quoting the page text that drove your decision.
If the excerpt is obviously an empty search page, say so in the rationale
and record ABSENT -- do NOT record SUPPORTS just because the query terms
appear on the page."""


# ---------------------------------------------------------------------------
# Invocation helper
# ---------------------------------------------------------------------------


def initial_state_from_input(evidence_input: EvidenceInput) -> dict[str, Any]:
    """Build the initial state dict for an evidence agent invocation."""
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
# Scorer subagent
# ---------------------------------------------------------------------------


class _ScorerState(AgentState):
    """Scorer subagent state: inherits messages from AgentState and adds
    the verdict fields tools write via ``Command(update=...)``."""

    alignment: NotRequired[str]
    rationale: NotRequired[str]


def build_scorer_subagent() -> Any:
    """Build the LLM-backed alignment scorer as a ``create_agent`` subagent.

    One inline ``@tool`` (``record_alignment``) writes the verdict into
    ``_ScorerState`` via ``Command(update=...)``. Model temperature is
    ``SCORER_TEMPERATURE`` (0.4) to give the LLM enough latitude to
    recognize degenerate pages (empty search results, login walls) as
    ABSENT rather than rubber-stamping keyword overlap.
    """
    model = ChatAnthropic(
        model=SCORER_MODEL,
        max_tokens=SCORER_MAX_TOKENS,
        temperature=SCORER_TEMPERATURE,
    )

    @tool
    def record_alignment(
        alignment: Literal["SUPPORTS", "CONTRADICTS", "PARTIAL", "ABSENT"],
        rationale: str,
        runtime: ToolRuntime,
    ) -> Command:
        """Record your alignment verdict for the fetched source.

        Args:
            alignment: One of SUPPORTS / CONTRADICTS / PARTIAL / ABSENT.
                Use ABSENT for empty search pages, login walls, or
                content that does not bear on the claim.
            rationale: 1-2 sentences citing the source wording that drove
                your verdict.
        """
        return Command(
            update={
                "alignment": alignment,
                "rationale": rationale,
                "messages": [
                    ToolMessage(
                        content=f"Recorded alignment={alignment}",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    return create_agent(
        model=model,
        tools=[record_alignment],
        system_prompt=_SCORER_SYSTEM_PROMPT,
        state_schema=_ScorerState,
        name=SCORER_NAME,
    )


def _format_scorer_prompt(claim_text: str, source: dict[str, Any]) -> str:
    """Build the user message for the scorer subagent."""
    excerpt = (source.get("content") or "")[:2000]
    return (
        f"Claim: {claim_text}\n\n"
        f"Source: {source.get('name', '')}\n"
        f"URL: {source.get('url', '')}\n\n"
        f"Content excerpt (first 2000 chars):\n"
        f"```\n{excerpt}\n```\n\n"
        "Decide alignment and call the record_alignment tool exactly once."
    )


# ---------------------------------------------------------------------------
# Agent construction (Functional API)
# ---------------------------------------------------------------------------


def build_evidence_agent() -> Any:
    """Build the evidence agent as a compiled LangGraph entrypoint.

    Returns:
        A compiled ``@entrypoint``-decorated workflow. Invoke with the
        initial state dict from :func:`initial_state_from_input`; the
        final return value is a dict with ``claimreview_matches``,
        ``domain_sources``, and ``best_confidence``.
    """
    extractor = WebContentExtractor(
        strategies=[
            TrafilaturaStrategy(),
            BeautifulSoupStrategy(),
            RawTextStrategy(),
        ],
        cache=FetchCache(),
    )
    scorer = build_scorer_subagent()

    @task
    async def _task_search_factchecks(state: dict[str, Any]) -> list[dict]:
        share_progress("Searching fact-check databases...")
        share_heartbeat(AGENT_NAME)
        matches = await search_factcheck_matches(
            claim_text=state.get("claim_text", ""),
            persons=state.get("persons"),
            organizations=state.get("organizations"),
        )
        share_heartbeat(AGENT_NAME)
        return matches

    @task
    async def _task_lookup_sources(state: dict[str, Any]) -> list[dict]:
        share_progress("Looking up domain-authoritative sources...")
        share_heartbeat(AGENT_NAME)
        sources = await lookup_sources(
            claim_text=state.get("claim_text", ""),
            domain=state.get("domain", "OTHER"),
            persons=state.get("persons"),
            organizations=state.get("organizations"),
            statistics=state.get("statistics"),
            dates=state.get("dates"),
            extractor=extractor,
        )
        share_heartbeat(AGENT_NAME)
        return sources

    @task
    async def _task_score_sources(claim_text: str, sources: list[dict]) -> list[dict]:
        if not sources:
            return []
        source = sources[0]
        share_progress(f"Scoring evidence from {source.get('name', '')}...")
        share_heartbeat(AGENT_NAME)

        prompt = _format_scorer_prompt(claim_text, source)
        config = {
            "configurable": {
                "thread_id": f"{SCORER_NAME}-{uuid.uuid4()}",
                "checkpoint_ns": "",
            }
        }
        try:
            result = await scorer.ainvoke(
                {"messages": [HumanMessage(content=prompt)]},
                config=config,
            )
        except Exception as exc:  # pragma: no cover -- defensive
            logger.warning("scorer subagent raised: %s", exc)
            return [
                {
                    "name": source.get("name", ""),
                    "url": source.get("url", ""),
                    "alignment": "ABSENT",
                    "rationale": f"scorer error: {exc}",
                }
            ]

        alignment = str(result.get("alignment") or "ABSENT").upper()
        rationale = str(result.get("rationale") or "")
        share_heartbeat(AGENT_NAME)
        return [
            {
                "name": source.get("name", ""),
                "url": source.get("url", ""),
                "alignment": alignment,
                "rationale": rationale,
            }
        ]

    @task
    def _task_format(claimreview: list[dict], scored: list[dict]) -> dict[str, Any]:
        return format_response(
            claimreview_matches=claimreview,
            scored_sources=scored,
        )

    @entrypoint(checkpointer=InMemorySaver())
    async def find_evidence(state: dict[str, Any]) -> dict[str, Any]:
        cr_future = _task_search_factchecks(state)
        src_future = _task_lookup_sources(state)
        claimreview = await cr_future
        sources = await src_future
        scored = await _task_score_sources(state.get("claim_text", ""), sources)
        return await _task_format(claimreview, scored)

    return find_evidence
