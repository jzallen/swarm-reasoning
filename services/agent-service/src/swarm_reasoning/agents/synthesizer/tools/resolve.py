"""resolve-observations tool: reads all upstream streams and applies epistemic resolution."""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.synthesizer.resolver import ObservationResolver
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


def _serialize_resolved(resolved) -> str:
    """Serialize a ResolvedObservationSet to JSON for downstream tools."""
    return json.dumps({
        "synthesis_signal_count": resolved.synthesis_signal_count,
        "warnings": resolved.warnings,
        "observations": [
            {
                "agent": obs.agent,
                "code": obs.code,
                "value": obs.value,
                "value_type": obs.value_type,
                "seq": obs.seq,
                "status": obs.status,
                "resolution_method": obs.resolution_method,
                "timestamp": obs.timestamp,
                "method": obs.method,
                "note": obs.note,
                "units": obs.units,
                "reference_range": obs.reference_range,
            }
            for obs in resolved.observations
        ],
        "excluded_count": len(resolved.excluded_observations),
    })


@tool
async def resolve_observations(
    run_id: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Resolve all upstream agent observations using epistemic status precedence.

    Reads the 10 upstream agent streams and applies the resolution algorithm:
    C-status > F-status; X excluded silently; P excluded with warning.

    Publishes a SYNTHESIS_SIGNAL_COUNT observation with the number of resolved
    signals.

    Args:
        run_id: The current verification run identifier.
        context: Injected AgentContext -- not exposed to the LLM.

    Returns:
        JSON string containing the resolved observation set with signal count,
        warnings, and individual observations.
    """
    resolver = ObservationResolver()
    resolved = await resolver.resolve(run_id, context.stream)

    await context.publish_obs(
        code=ObservationCode.SYNTHESIS_SIGNAL_COUNT,
        value=str(resolved.synthesis_signal_count),
        value_type=ValueType.NM,
        units="count",
        method="resolve_observations",
    )

    return _serialize_resolved(resolved)
