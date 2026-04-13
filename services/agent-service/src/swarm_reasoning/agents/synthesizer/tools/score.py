"""compute-confidence tool: deterministic weighted scoring of resolved observations."""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.synthesizer.models import ResolvedObservation, ResolvedObservationSet
from swarm_reasoning.agents.synthesizer.scorer import ConfidenceScorer
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


def _deserialize_resolved(resolved_json: str) -> ResolvedObservationSet:
    """Reconstruct a ResolvedObservationSet from the JSON produced by resolve_observations."""
    data = json.loads(resolved_json)
    observations = [
        ResolvedObservation(
            agent=obs["agent"],
            code=obs["code"],
            value=obs["value"],
            value_type=obs["value_type"],
            seq=obs["seq"],
            status=obs["status"],
            resolution_method=obs["resolution_method"],
            timestamp=obs["timestamp"],
            method=obs.get("method"),
            note=obs.get("note"),
            units=obs.get("units"),
            reference_range=obs.get("reference_range"),
        )
        for obs in data["observations"]
    ]
    return ResolvedObservationSet(
        observations=observations,
        synthesis_signal_count=data["synthesis_signal_count"],
        warnings=data.get("warnings", []),
    )


@tool
async def compute_confidence(
    resolved_json: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Compute a calibrated confidence score from resolved observations.

    Uses a deterministic weighted signal model (ADR-004) with five components:
    Domain Evidence (0.30), ClaimReview (0.25), Cross-Spectrum (0.15),
    Coverage Framing (0.15), Source Convergence (0.10).

    Returns None when signal count < 5 (UNVERIFIABLE). Publishes a
    CONFIDENCE_SCORE observation when a score is computed.

    Args:
        resolved_json: JSON string from resolve_observations containing the
            resolved observation set.
        context: Injected AgentContext -- not exposed to the LLM.

    Returns:
        JSON string with the confidence score (or null if unverifiable).
    """
    resolved = _deserialize_resolved(resolved_json)
    scorer = ConfidenceScorer()
    confidence_score = scorer.compute(resolved)

    if confidence_score is not None:
        await context.publish_obs(
            code=ObservationCode.CONFIDENCE_SCORE,
            value=f"{confidence_score:.4f}",
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
            method="compute_confidence",
        )

    return json.dumps({"score": confidence_score})
