"""LangGraphBase -- base class for LangGraph ReAct agents (ADR-016).

Extends FanoutBase to build a LangGraph ReAct agent via create_react_agent.
Subclasses provide _tools(), _system_prompt(), and _model_id(). AgentContext
is passed through LangGraph's context_schema for tool injection via
runtime.context in tool functions.
"""

from __future__ import annotations

import abc
import logging
import warnings

import redis.asyncio as aioredis
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

from swarm_reasoning.agents.fanout_base import ClaimContext, FanoutBase
from swarm_reasoning.agents.prompts import TOOL_USAGE_SUFFIX
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "claude-sonnet-4-20250514"


class LangGraphBase(FanoutBase):
    """Base class for agents backed by a LangGraph ReAct graph.

    Subclasses must implement:
        _tools()          — list of LangChain tools for the agent
        _system_prompt()  — agent system prompt (TOOL_USAGE_SUFFIX is appended)
        _primary_code()   — primary observation code for timeout fallback

    Optionally override:
        _model_id()  — Anthropic model identifier (default: claude-sonnet-4)
    """

    @abc.abstractmethod
    def _tools(self) -> list[BaseTool]:
        """Return tools available to the LangGraph agent."""

    @abc.abstractmethod
    def _system_prompt(self) -> str:
        """Return the system prompt for the LangGraph agent."""

    def _model_id(self) -> str:
        """Return the Anthropic model identifier."""
        return DEFAULT_MODEL_ID

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        # Lazy import to avoid import-time deprecation warnings
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

        claim_input = _format_claim_input(context)

        await graph.ainvoke(
            {"messages": [HumanMessage(content=claim_input)]},
            config={"context": agent_ctx},
        )

        # Sync observation count back to FanoutBase for STOP message
        self._seq = agent_ctx.seq_counter


def _format_claim_input(context: ClaimContext) -> str:
    """Format ClaimContext into a human message for the agent."""
    parts = [f"Claim: {context.normalized_claim}"]
    if context.domain != "OTHER":
        parts.append(f"Domain: {context.domain}")
    if context.persons:
        parts.append(f"Persons: {', '.join(context.persons)}")
    if context.organizations:
        parts.append(f"Organizations: {', '.join(context.organizations)}")
    if context.dates:
        parts.append(f"Dates: {', '.join(context.dates)}")
    if context.locations:
        parts.append(f"Locations: {', '.join(context.locations)}")
    if context.statistics:
        parts.append(f"Statistics: {', '.join(context.statistics)}")
    return "\n".join(parts)
