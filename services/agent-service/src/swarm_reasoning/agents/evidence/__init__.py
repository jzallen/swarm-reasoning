"""Evidence agent module -- ClaimReview lookups and domain evidence gathering.

Tools are in the ``tools`` subpackage; agent assembly is in ``agent.py``.
"""

from swarm_reasoning.agents.evidence.agent import (
    AGENT_NAME,
    build_evidence_agent,
    run_evidence_agent,
)
from swarm_reasoning.agents.evidence.models import EvidenceInput, EvidenceOutput

__all__ = [
    "AGENT_NAME",
    "EvidenceInput",
    "EvidenceOutput",
    "build_evidence_agent",
    "run_evidence_agent",
]
