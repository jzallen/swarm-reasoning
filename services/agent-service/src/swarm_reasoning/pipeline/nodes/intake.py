"""Intake pipeline node: URL-based claim extraction with human-in-the-loop selection.

The node runs in three internal stages around a LangGraph ``interrupt()``:

  Phase A (pure, pre-interrupt):
    fetch_content + decompose_claims on the source URL, producing extracted
    claims and article metadata.

  Interrupt:
    Pause the graph and surface the claim list to the caller. Resume with
    ``Command(resume=<int>)`` carrying a 1-based claim index.

  Phase B (pure, post-interrupt):
    classify_domain + extract_entities on the selected claim.

All observation writes happen exactly once, post-interrupt, in
``_publish_intake_observations``. Phase A and Phase B helpers are side-effect
free with respect to the Redis stream, so the node re-execution that
LangGraph performs on resume does not double-publish observations (sr-ld49).
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import RunnableConfig, interrupt

from swarm_reasoning.agents.intake import build_intake_agent, intake_output_from_state
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.nodes._inner_config import inner_agent_config
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

AGENT_NAME = "intake"

_ENTITY_ORDER: list[tuple[str, ObservationCode]] = [
    ("persons", ObservationCode.ENTITY_PERSON),
    ("organizations", ObservationCode.ENTITY_ORG),
    ("dates", ObservationCode.ENTITY_DATE),
    ("locations", ObservationCode.ENTITY_LOCATION),
    ("statistics", ObservationCode.ENTITY_STATISTIC),
]


async def _phase_a_extract(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Pure: URL → IntakeOutput dict (article meta + claims). No observation writes.

    Returns an :class:`IntakeOutput` projected from the agent's final
    state. The caller inspects ``error`` and ``extracted_claims`` to
    decide control flow.
    """
    url = state.get("claim_url") or state.get("claim_text", "")
    agent = build_intake_agent()
    result = await agent.ainvoke(
        {"messages": [("user", f"Process this URL: {url}")]},
        config=inner_agent_config(config, agent=AGENT_NAME),
    )
    return intake_output_from_state(result)


async def _phase_b_analyze(
    selected_claim: dict[str, Any],
    state: PipelineState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Pure: selected claim → domain + entities. No observation writes."""
    claim_text = selected_claim.get("claim_text", "")
    agent = build_intake_agent()
    result = await agent.ainvoke(
        {"messages": [("user", f"Classify and extract entities for this claim: {claim_text}")]},
        config=inner_agent_config(config, agent=AGENT_NAME),
    )
    structured = intake_output_from_state(result)
    return {
        "domain": structured.get("domain", "OTHER"),
        "entities": structured.get("entities", {}) or {},
    }


async def _publish_intake_observations(
    ctx: PipelineContext,
    *,
    url: str,
    selected: dict[str, Any],
    domain: str,
    entities: dict[str, list[str]],
) -> None:
    """Publish all intake observations in one shot, post-interrupt.

    Emits CLAIM_SOURCE_URL, CLAIM_TEXT, CLAIM_DOMAIN, and ENTITY_* in a
    deterministic order. Called exactly once per successful run so the
    Redis observation log (append-only, ADR-003) stays idempotent across
    the node re-execution triggered by ``Command(resume=)``.
    """
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_SOURCE_URL,
        value=url,
        value_type=ValueType.ST,
        method="fetch_content",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_TEXT,
        value=selected.get("claim_text", ""),
        value_type=ValueType.ST,
        method="decompose_claims",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_DOMAIN,
        value=domain,
        value_type=ValueType.ST,
        method="classify_domain",
    )
    for field_name, obs_code in _ENTITY_ORDER:
        for entity_value in entities.get(field_name, []) or []:
            await ctx.publish_observation(
                agent=AGENT_NAME,
                code=obs_code,
                value=entity_value,
                value_type=ValueType.ST,
                method="extract_entities",
            )


async def intake_node(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Unified intake node: Phase A → interrupt → Phase B → publish observations.

    Re-executes from the top on ``Command(resume=)``. All LangGraph-facing
    side effects (observation publishing) are deferred until after the
    interrupt so they fire exactly once per completed run.
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat(AGENT_NAME)

    url = state.get("claim_url") or state.get("claim_text", "")

    await ctx.publish_progress(AGENT_NAME, "Starting intake: fetching article...")

    phase_a = await _phase_a_extract(state, config)

    if phase_a.get("error"):
        await ctx.publish_progress(AGENT_NAME, f"Intake rejected: {phase_a['error']}")
        return {"errors": [phase_a["error"]]}

    claims = phase_a.get("extracted_claims") or []
    if not claims:
        await ctx.publish_progress(AGENT_NAME, "No factual claims found in article")
        return {"errors": ["NO_FACTUAL_CLAIMS"]}

    await ctx.publish_progress(AGENT_NAME, f"Found {len(claims)} claims for review")

    # Pause the graph. Caller resumes with Command(resume=<1-based index>).
    # article_text and article_accessed_at are deliberately excluded from the
    # payload (size + audit-field noise); the UI can re-fetch if needed.
    selected_index = interrupt(
        {
            "claims": claims,
            "article_title": phase_a.get("article_title", ""),
            "article_url": url,
            "article_author": phase_a.get("article_author"),
            "article_publisher": phase_a.get("article_publisher"),
            "article_published_at": phase_a.get("article_published_at"),
        }
    )

    ctx.heartbeat(AGENT_NAME)
    selected = claims[int(selected_index) - 1]

    await ctx.publish_progress(AGENT_NAME, "Analyzing selected claim...")
    phase_b = await _phase_b_analyze(selected, state, config)

    await _publish_intake_observations(
        ctx,
        url=url,
        selected=selected,
        domain=phase_b["domain"],
        entities=phase_b["entities"],
    )

    await ctx.publish_progress(AGENT_NAME, f"Analysis complete: domain={phase_b['domain']}")

    return {
        "extracted_claims": claims,
        "article_text": phase_a.get("article_text", ""),
        "article_title": phase_a.get("article_title", ""),
        "article_author": phase_a.get("article_author"),
        "article_publisher": phase_a.get("article_publisher"),
        "article_published_at": phase_a.get("article_published_at"),
        "article_accessed_at": phase_a.get("article_accessed_at"),
        "selected_claim": selected,
        "claim_text": selected.get("claim_text", ""),
        "claim_domain": phase_b["domain"],
        "entities": phase_b["entities"],
        "is_check_worthy": True,
    }
