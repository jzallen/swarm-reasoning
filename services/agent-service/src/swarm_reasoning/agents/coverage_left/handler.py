"""Coverage-left agent handler -- left-spectrum NewsAPI analysis."""

from __future__ import annotations

from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.coverage_core import CoverageHandler

AGENT_NAME = "coverage-left"


@register_handler("coverage-left")
class CoverageLeftHandler(CoverageHandler):
    AGENT_NAME = AGENT_NAME
    SPECTRUM = "left"
