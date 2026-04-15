"""Intake agent tools -- reusable functions for claim intake processing.

Each module exposes the core logic for one step of the intake pipeline:

- ``claim_intake`` -- structural validation (text, URL, date, dedup)
- ``domain_cls`` -- LLM-powered domain classification via Claude
- ``normalizer`` -- claim text normalization (lowercasing, hedge removal, pronoun resolution)
- ``scorer`` -- check-worthiness scoring with self-consistency
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
    call_claude,
)
from swarm_reasoning.agents.intake.tools.entity_extractor import (
    EntityExtractionResult,
    LLMUnavailableError,
    extract_entities_llm,
)
from swarm_reasoning.agents.intake.tools.normalizer import (
    MAX_NORMALIZED_LENGTH,
    NormalizeResult,
    normalize_claim_text,
)
from swarm_reasoning.agents.intake.tools.scorer import (
    CHECK_WORTHY_THRESHOLD,
    ScoreResult,
    is_check_worthy,
    score_claim_text,
)

__all__ = [
    "CHECK_WORTHY_THRESHOLD",
    "DOMAIN_VOCABULARY",
    "EntityExtractionResult",
    "LLMUnavailableError",
    "MAX_NORMALIZED_LENGTH",
    "NormalizeResult",
    "ScoreResult",
    "ValidationError",
    "build_prompt",
    "call_claude",
    "check_duplicate",
    "extract_entities_llm",
    "is_check_worthy",
    "normalize_claim_text",
    "normalize_date",
    "score_claim_text",
    "validate_claim_text",
    "validate_source_url",
]
