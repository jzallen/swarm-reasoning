"""Coverage tool: analyze headline sentiment and classify framing.

Computes VADER-style compound sentiment from article headlines and publishes
a COVERAGE_FRAMING observation with the CWE-encoded framing classification.
"""

from __future__ import annotations

from swarm_reasoning.agents.coverage.core import classify_framing, compute_compound_sentiment
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext


async def detect_coverage_framing(
    articles: list[dict],
    ctx: PipelineContext,
    agent_name: str,
) -> tuple[str, float]:
    """Analyze headline sentiment and publish COVERAGE_FRAMING observation.

    Returns (framing_cwe, compound_score).
    """
    if not articles:
        framing = "ABSENT^Not Covered^FCK"
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_FRAMING,
            value=framing,
            value_type=ValueType.CWE,
            method="detect_framing",
        )
        return framing, 0.0

    headlines = [a.get("title", "") for a in articles[:5] if a.get("title")]
    compound = compute_compound_sentiment(headlines)
    framing = classify_framing(compound)

    await ctx.publish_observation(
        agent=agent_name,
        code=ObservationCode.COVERAGE_FRAMING,
        value=framing,
        value_type=ValueType.CWE,
        method="detect_framing",
    )

    return framing, compound
