"""Evidence agent -- ClaimReview lookup + domain-source evidence gathering.

Built with LangGraph's Functional API (``@entrypoint`` + ``@task``). The
control flow is a straight-line deterministic pipeline:

    search_factchecks ─┐
                       ├─► score_evidence ─► format_response ─► END
    lookup_sources ────┘   (LLM subagent)

``search_factchecks`` and ``lookup_sources`` run concurrently; the LLM
subagent in ``score_evidence`` (colocated under
``tasks/score_evidence/``) judges alignment on fetched content and
returns SUPPORTS / CONTRADICTS / PARTIAL / ABSENT.

Pipeline integration (PipelineContext, observation publishing,
PipelineState <-> EvidenceInput translation) lives in the pipeline node
wrapper, not here.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.func import entrypoint, task

from swarm_reasoning.agents.evidence.models import EvidenceInput
from swarm_reasoning.agents.evidence.tasks import (
    format_response,
    lookup_sources,
    score_evidence,
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

AGENT_NAME = "evidence"


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
        scored = await score_evidence(state.get("claim_text", ""), sources)
        return await _task_format(claimreview, scored)

    return find_evidence
