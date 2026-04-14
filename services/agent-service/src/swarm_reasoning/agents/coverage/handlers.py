"""Coverage spectrum handlers -- left, center, right NewsAPI analysis."""

from __future__ import annotations

from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.coverage.core import CoverageHandler

AGENT_NAME_LEFT = "coverage-left"
AGENT_NAME_CENTER = "coverage-center"
AGENT_NAME_RIGHT = "coverage-right"


@register_handler("coverage-left")
class CoverageLeftHandler(CoverageHandler):
    AGENT_NAME = AGENT_NAME_LEFT
    SPECTRUM = "left"


@register_handler("coverage-center")
class CoverageCenterHandler(CoverageHandler):
    AGENT_NAME = AGENT_NAME_CENTER
    SPECTRUM = "center"


@register_handler("coverage-right")
class CoverageRightHandler(CoverageHandler):
    AGENT_NAME = AGENT_NAME_RIGHT
    SPECTRUM = "right"
