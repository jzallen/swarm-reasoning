"""Evidence scorer subagent task — colocated agent + tools + @task wrapper."""

from swarm_reasoning.agents.evidence.tasks.score_evidence.agent import (
    SCORER_NAME,
    build_scorer_subagent,
)
from swarm_reasoning.agents.evidence.tasks.score_evidence.task import score_evidence

__all__ = [
    "SCORER_NAME",
    "build_scorer_subagent",
    "score_evidence",
]
