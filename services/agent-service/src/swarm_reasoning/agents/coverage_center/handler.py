"""Coverage-center agent handler -- centrist-spectrum NewsAPI analysis."""

from __future__ import annotations

from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.coverage_core import CoverageHandler

AGENT_NAME = "coverage-center"


@register_handler("coverage-center")
class CoverageCenterHandler(CoverageHandler):
    AGENT_NAME = AGENT_NAME
    SPECTRUM = "center"
