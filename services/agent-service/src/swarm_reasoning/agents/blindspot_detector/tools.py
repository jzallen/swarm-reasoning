"""Blindspot analysis @tool definition for LangChain agents (ADR-004).

Provides analyze_blindspots as a @tool-decorated function that wraps coverage
asymmetry scoring, direction classification, and cross-spectrum corroboration.
AgentContext is injected at runtime via InjectedToolArg.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.blindspot_detector.analysis import (
    compute_blindspot_direction,
    compute_blindspot_score,
    compute_corroboration,
)
from swarm_reasoning.agents.blindspot_detector.models import CoverageSnapshot
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType

logger = logging.getLogger(__name__)


@tool
async def analyze_blindspots(
    coverage_data: Annotated[str, "JSON string of coverage data with left/center/right segments"],
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Analyze coverage data for blindspots across spectrum segments.

    Parses coverage data from left, center, and right spectrum segments,
    computes BLINDSPOT_SCORE (fraction of absent segments), BLINDSPOT_DIRECTION
    (which segments are missing), and CROSS_SPECTRUM_CORROBORATION (whether
    present segments agree). Publishes 3 observations.

    Args:
        coverage_data: JSON string with coverage information. Expected format:
            {"coverage": {"left": {"article_count": N, "framing": "..."}, ...},
             "source_convergence_score": float|null}
        context: Injected AgentContext -- not exposed to the LLM.

    Returns:
        Summary of blindspot analysis results.
    """
    data = json.loads(coverage_data) if isinstance(coverage_data, str) else coverage_data
    coverage = CoverageSnapshot.from_activity_input(data)

    score = compute_blindspot_score(coverage)
    direction = compute_blindspot_direction(coverage)
    corroboration, corroboration_note = compute_corroboration(coverage)

    # Publish BLINDSPOT_SCORE (seq 1)
    await context.publish_obs(
        code=ObservationCode.BLINDSPOT_SCORE,
        value=str(score),
        value_type=ValueType.NM,
        units="score",
        reference_range="0.0-1.0",
    )

    # Publish BLINDSPOT_DIRECTION (seq 2)
    await context.publish_obs(
        code=ObservationCode.BLINDSPOT_DIRECTION,
        value=direction,
        value_type=ValueType.CWE,
    )

    # Publish CROSS_SPECTRUM_CORROBORATION (seq 3)
    await context.publish_obs(
        code=ObservationCode.CROSS_SPECTRUM_CORROBORATION,
        value=corroboration,
        value_type=ValueType.CWE,
        note=corroboration_note,
    )

    direction_label = direction.split("^")[0]
    corroboration_label = corroboration.split("^")[0]
    return (
        f"Blindspot score: {score:.2f}, "
        f"direction: {direction_label}, "
        f"corroboration: {corroboration_label}"
    )
