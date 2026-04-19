"""Two-pass authoritative-source gathering for the evidence agent."""

from swarm_reasoning.agents.evidence.tasks.gather_sources.agent import (
    DISCOVERY_NAME,
    build_source_discovery_subagent,
)
from swarm_reasoning.agents.evidence.tasks.gather_sources.cache import SonarCache
from swarm_reasoning.agents.evidence.tasks.gather_sources.models import (
    DiscoveryResult,
    RecencyHint,
    SonarResult,
)
from swarm_reasoning.agents.evidence.tasks.gather_sources.task import gather_sources

__all__ = [
    "DISCOVERY_NAME",
    "DiscoveryResult",
    "RecencyHint",
    "SonarCache",
    "SonarResult",
    "build_source_discovery_subagent",
    "gather_sources",
]
