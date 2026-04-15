"""Coverage agent tools -- reusable functions for coverage analysis.

Each module exposes the core logic for one step of the coverage pipeline:

- ``build_search_query`` -- stop-word removal + truncation
- ``search_coverage`` -- NewsAPI query + COVERAGE_ARTICLE_COUNT obs
- ``detect_framing`` -- VADER-style sentiment → COVERAGE_FRAMING obs
- ``find_top_source`` -- credibility ranking → COVERAGE_TOP_SOURCE obs
"""

from swarm_reasoning.agents.coverage.tools.build_search_query import build_search_query
from swarm_reasoning.agents.coverage.tools.detect_framing import detect_coverage_framing
from swarm_reasoning.agents.coverage.tools.find_top_source import find_top_coverage_source
from swarm_reasoning.agents.coverage.tools.search_coverage import search_coverage

__all__ = [
    "build_search_query",
    "detect_coverage_framing",
    "find_top_coverage_source",
    "search_coverage",
]
