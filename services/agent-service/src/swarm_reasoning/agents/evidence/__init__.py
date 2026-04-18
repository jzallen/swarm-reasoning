"""Evidence agent module -- ClaimReview lookups and domain evidence gathering.

Tools live in the ``tools`` subpackage; agent assembly in ``agent.py``.
The pipeline node (``pipeline/nodes/evidence.py``) owns PipelineContext
translation and observation publishing.
"""

from swarm_reasoning.agents.evidence.agent import (
    AGENT_NAME,
    build_evidence_agent,
)
from swarm_reasoning.agents.evidence.models import (
    EvidenceInput,
    EvidenceInputError,
    EvidenceOutput,
    from_intake_output,
)

__all__ = [
    "AGENT_NAME",
    "EvidenceInput",
    "EvidenceInputError",
    "EvidenceOutput",
    "build_evidence_agent",
    "from_intake_output",
]
