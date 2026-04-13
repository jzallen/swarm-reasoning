"""LangChain @tool definitions for the source-validator agent."""

from swarm_reasoning.agents.source_validator.tools.aggregate import aggregate_citations
from swarm_reasoning.agents.source_validator.tools.convergence import compute_convergence_score
from swarm_reasoning.agents.source_validator.tools.extract import extract_urls
from swarm_reasoning.agents.source_validator.tools.validate import validate_urls

SOURCE_VALIDATOR_TOOLS = [
    extract_urls,
    validate_urls,
    compute_convergence_score,
    aggregate_citations,
]

__all__ = [
    "extract_urls",
    "validate_urls",
    "compute_convergence_score",
    "aggregate_citations",
    "SOURCE_VALIDATOR_TOOLS",
]
