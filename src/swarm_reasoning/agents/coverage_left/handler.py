"""Coverage-left agent handler -- left-spectrum NewsAPI analysis."""

from __future__ import annotations

from swarm_reasoning.agents.coverage_core import CoverageHandler
from swarm_reasoning.config import RedisConfig

AGENT_NAME = "coverage-left"


class CoverageLeftHandler(CoverageHandler):
    AGENT_NAME = AGENT_NAME
    SPECTRUM = "left"


_HANDLER: CoverageLeftHandler | None = None


def get_handler() -> CoverageLeftHandler:
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = CoverageLeftHandler()
    return _HANDLER
