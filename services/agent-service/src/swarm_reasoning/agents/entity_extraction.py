"""Re-export shim -- canonical location is now agents.intake.tools.entity_extractor."""

from swarm_reasoning.agents.intake.tools.entity_extractor import (
    EntityExtractionResult,
    LLMUnavailableError,
    extract_entities_llm,
)

__all__ = [
    "EntityExtractionResult",
    "LLMUnavailableError",
    "extract_entities_llm",
]
