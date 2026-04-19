"""Deterministic evidence-gathering tasks.

Raw async/sync functions live here; ``agent.py`` wraps them with
:func:`langgraph.func.task` decorators inside ``build_evidence_agent``.
No LLM or observation publishing -- those belong in the scorer subagent
and pipeline node respectively.
"""

from swarm_reasoning.agents.evidence.tasks.format_response import format_response
from swarm_reasoning.agents.evidence.tasks.lookup_sources import lookup_sources
from swarm_reasoning.agents.evidence.tasks.score_evidence import score_evidence
from swarm_reasoning.agents.evidence.tasks.search_factchecks import (
    search_factcheck_matches,
)

__all__ = [
    "format_response",
    "lookup_sources",
    "score_evidence",
    "search_factcheck_matches",
]
