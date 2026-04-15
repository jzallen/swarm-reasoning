"""Re-export shim -- canonical location is now agents.intake.tools.normalizer."""

from swarm_reasoning.agents.intake.tools.normalizer import (
    MAX_NORMALIZED_LENGTH,
    NormalizeResult,
    normalize_claim_text,
)

__all__ = [
    "MAX_NORMALIZED_LENGTH",
    "NormalizeResult",
    "normalize_claim_text",
]
