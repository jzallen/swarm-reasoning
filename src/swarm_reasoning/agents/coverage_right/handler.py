"""Coverage-right agent handler -- right-spectrum NewsAPI analysis."""

from __future__ import annotations

from swarm_reasoning.agents.coverage_core import CoverageHandler
from swarm_reasoning.config import RedisConfig

AGENT_NAME = "coverage-right"


class CoverageRightHandler(CoverageHandler):
    AGENT_NAME = AGENT_NAME
    SPECTRUM = "right"


_HANDLER: CoverageRightHandler | None = None


def get_handler() -> CoverageRightHandler:
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = CoverageRightHandler()
    return _HANDLER
