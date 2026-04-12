"""LangChain @tool definitions for the claim-detector agent."""

from swarm_reasoning.agents.claim_detector.tools.normalize import normalize_claim
from swarm_reasoning.agents.claim_detector.tools.score import score_check_worthiness

__all__ = [
    "normalize_claim",
    "score_check_worthiness",
]
