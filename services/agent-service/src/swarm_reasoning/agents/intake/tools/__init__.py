"""Intake agent tools -- reusable functions for claim intake processing.

Each module exposes the core logic for one step of the intake pipeline:

- ``claim_intake`` -- structural validation (text, URL, date, dedup)
- ``domain_classification`` -- LLM-powered domain classification via Claude
- ``entity_extractor`` -- LLM-powered named entity recognition
- ``fetch_content`` -- URL content fetching with trafilatura/BS4 extraction
"""

from swarm_reasoning.agents.intake.tools.claim_intake import (
    ValidationError,
    normalize_date,
    validate_claim_text,
    validate_source_url,
)
from swarm_reasoning.agents.intake.tools.domain_classification import (
    DOMAIN_VOCABULARY,
    build_prompt,
)
from swarm_reasoning.agents.intake.tools.entity_extractor import (
    EntityExtractionResult,
    LLMUnavailableError,
    extract_entities_llm,
)
from swarm_reasoning.agents.intake.tools.fetch_content import (
    FetchError,
    FetchResult,
    fetch_content,
    validate_url,
)

__all__ = [
    "DOMAIN_VOCABULARY",
    "EntityExtractionResult",
    "FetchError",
    "FetchResult",
    "LLMUnavailableError",
    "ValidationError",
    "build_prompt",
    "extract_entities_llm",
    "fetch_content",
    "normalize_date",
    "validate_claim_text",
    "validate_source_url",
    "validate_url",
]
