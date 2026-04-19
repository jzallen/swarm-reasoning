"""Evidence agent module -- ClaimReview lookups and domain evidence gathering.

Deterministic tasks live in the ``tasks`` subpackage; the LLM scorer
subagent and entrypoint orchestration live in ``agent.py``. The pipeline
node (``pipeline/nodes/evidence.py``) owns PipelineContext translation
and observation publishing.
"""

from swarm_reasoning.agents.evidence.agent import (
    AGENT_NAME,
    build_evidence_agent,
    initial_state_from_input,
)
from swarm_reasoning.agents.evidence.models import (
    EvidenceInput,
    EvidenceInputError,
    EvidenceOutput,
    from_intake_output,
)
from swarm_reasoning.agents.evidence.tasks.gather_sources import (
    build_source_discovery_subagent,
)
from swarm_reasoning.agents.evidence.tasks.score_evidence import build_scorer_subagent

__all__ = [
    "AGENT_NAME",
    "EvidenceInput",
    "EvidenceInputError",
    "EvidenceOutput",
    "build_evidence_agent",
    "build_scorer_subagent",
    "build_source_discovery_subagent",
    "from_intake_output",
    "initial_state_from_input",
]
