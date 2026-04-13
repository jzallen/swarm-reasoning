"""ClaimReview matcher handler -- LangGraph ReAct agent (ADR-004, ADR-016).

Uses the search_factchecks @tool to query the Google Fact Check Tools API,
score matches via TF-IDF cosine similarity, and publish CLAIMREVIEW_*
observations. The LLM decides when and how to call the tool; the tool layer
enforces observation schema validity.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.evidence.tools import search_factchecks
from swarm_reasoning.agents.langgraph_base import LangGraphBase
from swarm_reasoning.agents.observation_tools import publish_progress
from swarm_reasoning.models.observation import ObservationCode

AGENT_NAME = "claimreview-matcher"


@register_handler("claimreview-matcher")
class ClaimReviewMatcherHandler(LangGraphBase):
    """Queries Google Fact Check Tools API via LangGraph ReAct agent."""

    AGENT_NAME = AGENT_NAME

    def _tools(self) -> list[BaseTool]:
        return [search_factchecks, publish_progress]

    def _system_prompt(self) -> str:
        return (
            "You are a fact-check lookup agent. Your job is to search for "
            "existing fact-checks of the given claim using the search_factchecks "
            "tool.\n\n"
            "Steps:\n"
            "1. Use publish_progress to announce you are searching fact-check "
            "databases.\n"
            "2. Call search_factchecks with the claim text and any provided "
            "person/organization entities.\n"
            "3. Use publish_progress to report the outcome (match found or "
            "no match).\n\n"
            "Call search_factchecks exactly once. Do not fabricate results."
        )

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.CLAIMREVIEW_MATCH
