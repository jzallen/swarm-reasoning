"""Re-export shim -- canonical location is now agents.intake.tools.scorer."""

from swarm_reasoning.agents.intake.tools.scorer import (
    CHECK_WORTHY_THRESHOLD,
    MAX_RETRIES,
    ScoreResult,
    is_check_worthy,
    score_claim_text,
)

__all__ = [
    "CHECK_WORTHY_THRESHOLD",
    "MAX_RETRIES",
    "ScoreResult",
    "is_check_worthy",
    "score_claim_text",
]
