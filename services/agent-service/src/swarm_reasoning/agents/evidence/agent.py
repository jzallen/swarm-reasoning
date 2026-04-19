"""Evidence agent -- ClaimReview lookup + Sonar-driven source gathering.

Built with LangGraph's Functional API (``@entrypoint`` + ``@task``). The
control flow is a straight-line deterministic pipeline:

    search_factchecks ─┐
                       ├─► score_evidence ─► format_response ─► END
    gather_sources  ───┘   (LLM scorer subagent)

``search_factchecks`` and ``gather_sources`` run concurrently;
``gather_sources`` runs the two-pass Haiku-discovery + Perplexity-Sonar
flow defined in :mod:`...tasks.gather_sources`. ``score_evidence``
judges alignment of the fetched content via its own scorer subagent
(:mod:`...tasks.score_evidence`).

Pipeline integration (PipelineContext, observation publishing,
PipelineState <-> EvidenceInput translation) lives in the pipeline node
wrapper, not here.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.func import entrypoint, task

if TYPE_CHECKING:
    from swarm_reasoning.agents.evidence.models import EvidenceInput

AGENT_NAME = "evidence"


def initial_state_from_input(evidence_input: EvidenceInput) -> dict[str, Any]:
    """Build the initial state dict for an evidence agent invocation."""
    return {
        "claim_text": evidence_input.get("claim_text", ""),
        "domain": evidence_input.get("domain", "OTHER"),
        "persons": evidence_input.get("persons", []),
        "organizations": evidence_input.get("organizations", []),
        "dates": evidence_input.get("dates", []),
        "locations": evidence_input.get("locations", []),
        "statistics": evidence_input.get("statistics", []),
    }


def build_evidence_agent() -> Any:
    """Build the evidence agent as a compiled LangGraph entrypoint.

    Sonar response caching is owned by :func:`sonar_search` and gated by
    the ``SONAR_CACHE`` env var; this builder takes no cache arguments.

    Returns:
        A compiled ``@entrypoint``-decorated workflow. Invoke with the
        initial state dict from :func:`initial_state_from_input`; the
        final return value is a dict with ``claimreview_matches``,
        ``domain_sources``, and ``best_confidence``.
    """
    from swarm_reasoning.agents.evidence.tasks import build_source_discovery_subagent
    from swarm_reasoning.agents.messaging import share_heartbeat, share_progress
    from swarm_reasoning.agents.web import (
        BeautifulSoupStrategy,
        FetchCache,
        RawTextStrategy,
        TrafilaturaStrategy,
        WebContentExtractor,
    )

    extractor = WebContentExtractor(
        strategies=[
            TrafilaturaStrategy(),
            BeautifulSoupStrategy(),
            RawTextStrategy(),
        ],
        cache=FetchCache(),
    )
    discovery_subagent = build_source_discovery_subagent()

    @task
    async def _task_search_factchecks(state: dict[str, Any]) -> list[dict]:
        from swarm_reasoning.agents.evidence.tasks import search_factcheck_matches

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
    async def _task_gather_sources(state: dict[str, Any]) -> list[dict]:
        from swarm_reasoning.agents.evidence.tasks import gather_sources
        from swarm_reasoning.agents.evidence.tasks.gather_sources import DISCOVERY_NAME

        share_progress("Discovering authoritative sources...")
        share_heartbeat(AGENT_NAME)
        config = {
            "configurable": {
                "thread_id": f"{DISCOVERY_NAME}-{uuid.uuid4()}",
                "checkpoint_ns": "",
            }
        }
        sources = await gather_sources(
            claim_text=state.get("claim_text", ""),
            domain=state.get("domain", "OTHER"),
            persons=state.get("persons"),
            organizations=state.get("organizations"),
            statistics=state.get("statistics"),
            dates=state.get("dates"),
            extractor=extractor,
            subagent=discovery_subagent,
            config=config,
        )
        share_heartbeat(AGENT_NAME)
        return sources

    @task
    def _task_format(claimreview: list[dict], scored: list[dict]) -> dict[str, Any]:
        from swarm_reasoning.agents.evidence.tasks import format_response

        return format_response(
            claimreview_matches=claimreview,
            scored_sources=scored,
        )

    @entrypoint(checkpointer=InMemorySaver())
    async def find_evidence(state: dict[str, Any]) -> dict[str, Any]:
        from swarm_reasoning.agents.evidence.tasks import score_evidence

        claim_review_future = _task_search_factchecks(state)
        sources_future = _task_gather_sources(state)
        claimreview = await claim_review_future
        sources = await sources_future
        scored = await score_evidence(state.get("claim_text", ""), sources)
        return await _task_format(claimreview, scored)

    return find_evidence
