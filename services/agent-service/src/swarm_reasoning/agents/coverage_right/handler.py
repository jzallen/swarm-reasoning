"""Coverage-right agent handler -- right-spectrum NewsAPI analysis."""

from __future__ import annotations

from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.coverage_core import CoverageHandler

AGENT_NAME = "coverage-right"


@register_handler("coverage-right")
class CoverageRightHandler(CoverageHandler):
    AGENT_NAME = AGENT_NAME
    SPECTRUM = "right"
