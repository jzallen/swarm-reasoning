"""Blindspot detector handler -- LangGraph ReAct agent (ADR-004, ADR-016).

Phase 3 agent: receives cross-agent coverage data as Temporal activity input,
uses the analyze_blindspots @tool to compute BLINDSPOT_SCORE,
BLINDSPOT_DIRECTION, and CROSS_SPECTRUM_CORROBORATION, then publishes
observations to the agent's Redis Stream.
"""

from __future__ import annotations

import json
import logging
import warnings

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

import redis.asyncio as aioredis

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.blindspot_detector.tools import analyze_blindspots
from swarm_reasoning.agents.fanout_base import ClaimContext, FanoutBase
from swarm_reasoning.agents.langgraph_base import LangGraphBase
from swarm_reasoning.agents.observation_tools import publish_progress
from swarm_reasoning.agents.prompts import TOOL_USAGE_SUFFIX
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "blindspot-detector"


@register_handler("blindspot-detector")
class BlindspotDetectorHandler(LangGraphBase):
    """Orchestrates coverage asymmetry analysis via LangGraph ReAct agent.

    Overrides ``_execute()`` because blindspot-detector receives coverage data
    via ``cross_agent_data`` in the Temporal activity input, rather than from
    upstream Phase 1 streams.
    """

    AGENT_NAME = AGENT_NAME

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._cross_agent_data: dict = {}

    def _tools(self) -> list[BaseTool]:
        return [analyze_blindspots, publish_progress]

    def _system_prompt(self) -> str:
        return (
            "You are a coverage blindspot detector. Your job is to analyze "
            "coverage data from left-leaning, centrist, and right-leaning "
            "sources to detect blindspots and cross-spectrum corroboration.\n\n"
            "Steps:\n"
            "1. Use publish_progress to announce you are analyzing coverage "
            "blindspots.\n"
            "2. Call analyze_blindspots with the coverage data JSON provided.\n"
            "3. Use publish_progress to report the results (blindspot score, "
            "direction, and corroboration status).\n\n"
            "Call analyze_blindspots exactly once with the full coverage data. "
            "Do not fabricate results."
        )

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.BLINDSPOT_SCORE

    def _primary_value_type(self) -> ValueType:
        return ValueType.NM

    def _timeout_value(self) -> str:
        return "1.0"

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput:
        """Override to extract cross_agent_data before running base flow."""
        self._cross_agent_data = input.cross_agent_data or {}
        return await super().run(input)

    async def _load_upstream_context(self, stream: ReasoningStream, run_id: str) -> ClaimContext:
        """Blindspot-detector uses cross_agent_data; skip Phase 1 context loading."""
        return ClaimContext()

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        """Custom _execute that passes coverage data instead of claim context."""
        from langgraph.prebuilt import create_react_agent

        agent_ctx = AgentContext(
            stream=stream,
            redis_client=redis_client,
            run_id=run_id,
            sk=sk,
            agent_name=self.AGENT_NAME,
        )

        model = ChatAnthropic(model=self._model_id())
        tools = self._tools()
        prompt = self._system_prompt() + TOOL_USAGE_SUFFIX

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="create_react_agent has been moved",
                category=DeprecationWarning,
            )
            graph = create_react_agent(
                model=model,
                tools=tools,
                prompt=prompt,
                context_schema=AgentContext,
            )

        coverage_json = json.dumps(self._cross_agent_data, indent=2)
        message = (
            "Analyze the following coverage data for blindspots:\n\n"
            f"{coverage_json}"
        )

        await graph.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config={"context": agent_ctx},
        )

        self._seq = agent_ctx.seq_counter
