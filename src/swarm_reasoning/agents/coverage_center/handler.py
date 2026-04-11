"""Coverage-center agent handler -- centrist-spectrum NewsAPI analysis."""

from __future__ import annotations

from swarm_reasoning.agents.coverage_core import CoverageHandler
from swarm_reasoning.config import RedisConfig

AGENT_NAME = "coverage-center"


class CoverageCenterHandler(CoverageHandler):
    AGENT_NAME = AGENT_NAME
    SPECTRUM = "center"


_HANDLER: CoverageCenterHandler | None = None


def get_handler() -> CoverageCenterHandler:
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = CoverageCenterHandler()
    return _HANDLER
