"""Intake agent tools -- reusable functions for claim intake processing.

Each module exposes the core logic for one step of the intake pipeline:

- ``claim_intake`` -- structural validation (text, URL, date, dedup)
- ``domain_cls`` -- LLM-powered domain classification via Claude
- ``entity_extractor`` -- LLM-powered named entity recognition
"""

from swarm_reasoning.agents.intake.tools.claim_intake import (
    ValidationError,
    check_duplicate,
    normalize_date,
    validate_claim_text,
    validate_source_url,
)
from swarm_reasoning.agents.intake.tools.domain_cls import (
    DOMAIN_VOCABULARY,
    build_prompt,
)
from swarm_reasoning.agents.intake.tools.entity_extractor import (
    EntityExtractionResult,
    LLMUnavailableError,
    extract_entities_llm,
)

__all__ = [
    "DOMAIN_VOCABULARY",
    "EntityExtractionResult",
    "LLMUnavailableError",
    "ValidationError",
    "build_prompt",
    "check_duplicate",
    "extract_entities_llm",
    "normalize_date",
    "validate_claim_text",
    "validate_source_url",
]
