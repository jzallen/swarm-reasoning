"""LangChain tools for the ingestion agent."""

from swarm_reasoning.agents.ingestion_agent.tools.claim_intake import (
    IngestionResult,
    ingest_claim,
)
from swarm_reasoning.agents.ingestion_agent.tools.domain_cls import (
    ClassificationResult,
    classify_domain,
)

__all__ = [
    "ClassificationResult",
    "IngestionResult",
    "classify_domain",
    "ingest_claim",
]
