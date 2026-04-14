"""SynthesizerHandler -- LangGraph ReAct agent for verdict synthesis (ADR-004, ADR-016).

Final agent in the execution DAG: a LangGraph ReAct agent that orchestrates
four @tool definitions (resolve_observations, compute_confidence, map_verdict,
generate_narrative) to read all 10 upstream agent streams and produce a
confidence-scored verdict with narrative.

The LLM decides the tool call sequence; each tool enforces observation schema
validity and publishes its own observations via AgentContext.
"""

from __future__ import annotations

import json
import logging
import warnings

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

import redis.asyncio as aioredis

from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.fanout_base import ClaimContext
from swarm_reasoning.agents.langgraph_base import LangGraphBase
from swarm_reasoning.agents.observation_tools import publish_progress
from swarm_reasoning.agents.prompts import TOOL_USAGE_SUFFIX
from swarm_reasoning.agents.synthesizer.tools import (
    compute_confidence,
    generate_narrative,
    map_verdict,
    resolve_observations,
)
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.models.stream import Phase
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "synthesizer"


@register_handler("synthesizer")
class SynthesizerHandler(LangGraphBase):
    """Orchestrates verdict synthesis via LangGraph ReAct agent.

    Overrides ``_execute()`` because the synthesizer reads all upstream agent
    streams via ``resolve_observations`` (keyed by run_id), rather than
    receiving claim context from Phase 1 streams.
    """

    AGENT_NAME = AGENT_NAME

    def _tools(self) -> list[BaseTool]:
        return [
            resolve_observations,
            compute_confidence,
            map_verdict,
            generate_narrative,
            publish_progress,
        ]

    def _system_prompt(self) -> str:
        return (
            "You are a verdict synthesis agent. Your job is to synthesize all "
            "upstream agent observations into a final confidence-scored verdict "
            "with a human-readable narrative.\n\n"
            "Steps:\n"
            "1. Use publish_progress to announce you are beginning synthesis.\n"
            "2. Call resolve_observations with the run_id to gather and resolve "
            "all upstream agent observations.\n"
            "3. Call compute_confidence with the resolved_json output.\n"
            "4. Call map_verdict with the confidence_score and resolved_json.\n"
            "5. Call generate_narrative with the resolved_json, verdict_code, "
            "confidence_score, override_reason, signal_count, and "
            "warnings_json.\n"
            "6. Use publish_progress to announce the final verdict.\n\n"
            "You MUST call these tools in the order listed. Each tool requires "
            "output from the previous one. Do not skip tools or fabricate "
            "results."
        )

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.VERDICT

    def _primary_value_type(self) -> ValueType:
        return ValueType.CWE

    def _timeout_value(self) -> str:
        return "UNVERIFIABLE^Timeout^POLITIFACT"

    def _phase(self) -> Phase:
        return Phase.SYNTHESIS

    async def _load_upstream_context(
        self, stream: ReasoningStream, run_id: str
    ) -> ClaimContext:
        """Synthesizer reads ALL streams via resolve_observations; skip Phase 1 loading."""
        return ClaimContext()

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        """Custom _execute that passes run_id instead of claim context."""
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

        message = (
            f"Begin synthesis for run_id: {run_id}\n\n"
            "Call resolve_observations, then compute_confidence, then "
            "map_verdict, then generate_narrative — in that order."
        )

        await graph.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config={"context": agent_ctx},
        )

        self._seq = agent_ctx.seq_counter
