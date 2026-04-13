"""generate-narrative tool: LLM-powered verdict narrative with fallback template."""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator
from swarm_reasoning.agents.synthesizer.tools.score import _deserialize_resolved
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


@tool
async def generate_narrative(
    resolved_json: str,
    verdict_code: str,
    confidence_score: float | None,
    override_reason: str,
    signal_count: int,
    warnings_json: str = "[]",
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Generate a human-readable verdict narrative.

    Attempts LLM generation (Claude Haiku, 5s timeout) with structured context
    from the resolved observations. Falls back to a template-based narrative
    on failure or if the result is too short.

    Publishes a VERDICT_NARRATIVE observation.

    Args:
        resolved_json: JSON string from resolve_observations.
        verdict_code: The mapped verdict code (e.g. TRUE, FALSE).
        confidence_score: The computed confidence score, or None if unverifiable.
        override_reason: ClaimReview override reason (empty string if none).
        signal_count: Number of resolved signals.
        warnings_json: JSON array of warning strings from resolution.
        context: Injected AgentContext -- not exposed to the LLM.

    Returns:
        The generated narrative text (200-1000 characters).
    """
    resolved = _deserialize_resolved(resolved_json)
    warnings = json.loads(warnings_json)

    generator = NarrativeGenerator()
    narrative = await generator.generate(
        resolved=resolved,
        verdict=verdict_code,
        confidence_score=confidence_score,
        override_reason=override_reason,
        warnings=warnings,
        signal_count=signal_count,
    )

    await context.publish_obs(
        code=ObservationCode.VERDICT_NARRATIVE,
        value=narrative,
        value_type=ValueType.TX,
        method="generate_narrative",
    )

    return narrative
