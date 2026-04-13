"""map-verdict tool: threshold mapping with ClaimReview override."""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.synthesizer.mapper import VerdictMapper
from swarm_reasoning.agents.synthesizer.tools.score import _deserialize_resolved
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


@tool
async def map_verdict(
    confidence_score: float | None,
    resolved_json: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Map a confidence score to a PolitiFact verdict with ClaimReview override.

    Uses fixed threshold bands to map the score to one of: TRUE, MOSTLY_TRUE,
    HALF_TRUE, MOSTLY_FALSE, FALSE, PANTS_FIRE, or UNVERIFIABLE. When a
    high-confidence ClaimReview match disagrees with the swarm verdict, the
    ClaimReview verdict overrides.

    Publishes VERDICT and SYNTHESIS_OVERRIDE_REASON observations.

    Args:
        confidence_score: The computed confidence score (0.0-1.0), or None
            if unverifiable.
        resolved_json: JSON string from resolve_observations containing the
            resolved observation set.
        context: Injected AgentContext -- not exposed to the LLM.

    Returns:
        JSON string with verdict_code, verdict_cwe, and override_reason.
    """
    resolved = _deserialize_resolved(resolved_json)
    mapper = VerdictMapper()
    verdict_code, verdict_cwe, override_reason = mapper.map_verdict(
        confidence_score, resolved
    )

    await context.publish_obs(
        code=ObservationCode.VERDICT,
        value=verdict_cwe,
        value_type=ValueType.CWE,
        method="map_verdict",
    )

    await context.publish_obs(
        code=ObservationCode.SYNTHESIS_OVERRIDE_REASON,
        value=override_reason,
        value_type=ValueType.ST,
        method="map_verdict",
    )

    return json.dumps({
        "verdict_code": verdict_code,
        "verdict_cwe": verdict_cwe,
        "override_reason": override_reason,
    })
