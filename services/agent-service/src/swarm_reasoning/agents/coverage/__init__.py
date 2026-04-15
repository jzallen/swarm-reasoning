"""Coverage agent module -- spectrum-parameterized NewsAPI analysis.

Exposes the coverage agent factory and typed I/O models for use by the
pipeline node wrappers in ``swarm_reasoning.pipeline.nodes``.
"""

from swarm_reasoning.agents.coverage.agent import create_agent
from swarm_reasoning.agents.coverage.models import CoverageInput, CoverageOutput

__all__ = [
    "CoverageInput",
    "CoverageOutput",
    "create_agent",
]
