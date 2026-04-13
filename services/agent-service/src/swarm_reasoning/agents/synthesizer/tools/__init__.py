"""LangChain @tool definitions for the synthesizer agent."""

from swarm_reasoning.agents.synthesizer.tools.map_verdict import map_verdict
from swarm_reasoning.agents.synthesizer.tools.narrate import generate_narrative
from swarm_reasoning.agents.synthesizer.tools.resolve import resolve_observations
from swarm_reasoning.agents.synthesizer.tools.score import compute_confidence

__all__ = [
    "resolve_observations",
    "compute_confidence",
    "map_verdict",
    "generate_narrative",
]
