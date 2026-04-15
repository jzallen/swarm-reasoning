"""Synthesizer agent -- Phase 3 verdict synthesis (ADR-016).

Exposes the synthesizer StateGraph and typed I/O models for use by the
pipeline node wrapper in ``swarm_reasoning.pipeline.nodes.synthesizer``.
"""

from swarm_reasoning.agents.synthesizer.agent import (
    AGENT_NAME,
    build_synthesizer_graph,
    run_synthesizer,
    synthesizer_graph,
)
from swarm_reasoning.agents.synthesizer.models import (
    ResolvedObservation,
    ResolvedObservationSet,
    SynthesizerInput,
    SynthesizerOutput,
)

__all__ = [
    "AGENT_NAME",
    "build_synthesizer_graph",
    "run_synthesizer",
    "synthesizer_graph",
    "ResolvedObservation",
    "ResolvedObservationSet",
    "SynthesizerInput",
    "SynthesizerOutput",
]
