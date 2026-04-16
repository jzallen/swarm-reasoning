"""Intake pipeline node: two-phase URL-based claim extraction and analysis.

Implements the intake agent's two-phase interaction within the pipeline:

  Phase A (URL → claims):
    User submits URL → fetch_content → decompose_claims → return extracted
    claims to the user for selection.

  Phase B (selection → analysis):
    User selects a claim → classify_domain → extract_entities → publish
    final observations.

The pipeline graph routes between phases based on PipelineState: if
``extracted_claims`` is empty, run Phase A; if ``selected_claim`` is
present, run Phase B.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import RunnableConfig

from swarm_reasoning.agents.intake import build_intake_agent
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

AGENT_NAME = "intake"

# Deterministic entity publish order
_ENTITY_ORDER: list[tuple[str, ObservationCode]] = [
    ("persons", ObservationCode.ENTITY_PERSON),
    ("organizations", ObservationCode.ENTITY_ORG),
    ("dates", ObservationCode.ENTITY_DATE),
    ("locations", ObservationCode.ENTITY_LOCATION),
    ("statistics", ObservationCode.ENTITY_STATISTIC),
]


async def intake_phase_a(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Phase A: URL submission → extracted claims.

    Invokes the intake agent with the source URL. The agent runs
    fetch_content and decompose_claims, returning up to 5 factual claims
    for user selection.

    Returns state updates with ``extracted_claims`` and ``article_text``.
    On failure (bad URL, no claims), returns ``error``.
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat(AGENT_NAME)

    url = state.get("claim_url") or state.get("claim_text", "")

    await ctx.publish_progress(AGENT_NAME, "Starting intake: fetching article...")

    agent = build_intake_agent()
    result = await agent.ainvoke(
        {"messages": [("user", f"Process this URL: {url}")]},
        config=config,
    )

    ctx.heartbeat(AGENT_NAME)

    structured = result.get("structured_response", {})

    if structured.get("error"):
        await ctx.publish_progress(AGENT_NAME, f"Intake rejected: {structured['error']}")
        return {
            "errors": [structured["error"]],
        }

    claims = structured.get("extracted_claims", [])
    if not claims:
        await ctx.publish_progress(AGENT_NAME, "No factual claims found in article")
        return {
            "errors": ["NO_FACTUAL_CLAIMS"],
        }

    # Publish source URL observation
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_SOURCE_URL,
        value=url,
        value_type=ValueType.ST,
        method="fetch_content",
    )

    await ctx.publish_progress(AGENT_NAME, f"Found {len(claims)} claims for review")

    return {
        "extracted_claims": claims,
        "article_text": structured.get("article_text", ""),
        "article_title": structured.get("article_title", ""),
    }


async def intake_phase_b(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Phase B: selected claim → domain classification + entity extraction.

    Invokes the intake agent with the user's selected claim. The agent
    runs classify_domain and extract_entities on that claim.

    Returns state updates with ``claim_domain``, ``entities``, and
    ``selected_claim``.
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat(AGENT_NAME)

    selected = state.get("selected_claim", {})
    claim_text = selected.get("claim_text", "")

    await ctx.publish_progress(AGENT_NAME, "Analyzing selected claim...")

    agent = build_intake_agent()
    result = await agent.ainvoke(
        {"messages": [("user", f"Classify and extract entities for this claim: {claim_text}")]},
        config=config,
    )

    ctx.heartbeat(AGENT_NAME)

    structured = result.get("structured_response", {})

    domain = structured.get("domain", "OTHER")
    entities = structured.get("entities", {})

    # Publish CLAIM_TEXT from selected claim (not raw input)
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_TEXT,
        value=claim_text,
        value_type=ValueType.ST,
        method="decompose_claims",
    )

    # Publish domain classification
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_DOMAIN,
        value=domain,
        value_type=ValueType.ST,
        method="classify_domain",
    )

    # Publish entity observations in deterministic order
    for field_name, obs_code in _ENTITY_ORDER:
        for entity_value in entities.get(field_name, []):
            await ctx.publish_observation(
                agent=AGENT_NAME,
                code=obs_code,
                value=entity_value,
                value_type=ValueType.ST,
                method="extract_entities",
            )

    await ctx.publish_progress(AGENT_NAME, f"Analysis complete: domain={domain}")

    return {
        "claim_domain": domain,
        "entities": entities,
        "claim_text": claim_text,
        "is_check_worthy": True,
    }


def should_run_phase_b(state: PipelineState) -> bool:
    """Routing condition: True if Phase A is done and user selected a claim."""
    return bool(state.get("selected_claim"))


async def intake_node(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Unified intake node: routes to Phase A or Phase B based on state.

    - If ``selected_claim`` is present → Phase B (classify + extract)
    - Otherwise → Phase A (fetch + decompose)
    """
    if should_run_phase_b(state):
        return await intake_phase_b(state, config)
    return await intake_phase_a(state, config)
