"""Unit tests for SynthesizerHandler (LangGraphBase conversion)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.langgraph_base import LangGraphBase
from swarm_reasoning.agents.observation_tools import publish_progress
from swarm_reasoning.agents.synthesizer.handler import SynthesizerHandler
from swarm_reasoning.agents.synthesizer.tools import (
    compute_confidence,
    generate_narrative,
    map_verdict,
    resolve_observations,
)
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.models.stream import Phase, StartMessage, StopMessage

_RUN_ID = "run-synth-001"


def _make_input() -> MagicMock:
    inp = MagicMock()
    inp.run_id = _RUN_ID
    inp.agent_name = "synthesizer"
    inp.claim_text = "Test claim"
    return inp


def _make_stream_mock() -> AsyncMock:
    """Stream mock; synthesizer skips upstream loading so no streams needed."""
    stream_mock = AsyncMock()
    stream_mock.read_range = AsyncMock(return_value=[])
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()
    return stream_mock


class TestHandlerStructure:
    """Verify the handler extends LangGraphBase correctly."""

    def test_extends_langgraph_base(self):
        assert issubclass(SynthesizerHandler, LangGraphBase)

    def test_agent_name(self):
        handler = SynthesizerHandler()
        assert handler.AGENT_NAME == "synthesizer"

    def test_tools_includes_all_synthesis_tools(self):
        handler = SynthesizerHandler()
        tools = handler._tools()
        tool_names = [t.name for t in tools]
        assert "resolve_observations" in tool_names
        assert "compute_confidence" in tool_names
        assert "map_verdict" in tool_names
        assert "generate_narrative" in tool_names
        assert "publish_progress" in tool_names

    def test_primary_code_is_verdict(self):
        handler = SynthesizerHandler()
        assert handler._primary_code() == ObservationCode.VERDICT

    def test_primary_value_type_is_cwe(self):
        handler = SynthesizerHandler()
        assert handler._primary_value_type() == ValueType.CWE

    def test_phase_is_synthesis(self):
        handler = SynthesizerHandler()
        assert handler._phase() == Phase.SYNTHESIS

    def test_system_prompt_mentions_tools(self):
        handler = SynthesizerHandler()
        prompt = handler._system_prompt()
        assert isinstance(prompt, str)
        assert "resolve_observations" in prompt
        assert "compute_confidence" in prompt
        assert "map_verdict" in prompt
        assert "generate_narrative" in prompt


class TestHandlerExecution:
    """Verify the handler runs through the LangGraph ReAct agent."""

    @pytest.mark.asyncio
    async def test_creates_react_agent_with_tools(self):
        """Verifies all synthesis tools are passed to create_react_agent."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={"messages": []})

        captured_kwargs = {}

        def fake_create(*, model, tools, prompt, context_schema):
            captured_kwargs["tools"] = tools
            captured_kwargs["context_schema"] = context_schema
            return mock_graph

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch("swarm_reasoning.agents.langgraph_base.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                side_effect=fake_create,
            ),
        ):
            handler = SynthesizerHandler()
            await handler.run(_make_input())

        assert captured_kwargs["context_schema"] is AgentContext
        tool_names = [t.name for t in captured_kwargs["tools"]]
        assert "resolve_observations" in tool_names
        assert "compute_confidence" in tool_names
        assert "map_verdict" in tool_names
        assert "generate_narrative" in tool_names
        assert "publish_progress" in tool_names

    @pytest.mark.asyncio
    async def test_passes_run_id_to_agent(self):
        """Verifies run_id is included in the HumanMessage."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        captured_inputs = {}

        async def fake_ainvoke(inputs, config=None):
            captured_inputs.update(inputs)
            return {"messages": []}

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch("swarm_reasoning.agents.langgraph_base.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = SynthesizerHandler()
            await handler.run(_make_input())

        msgs = captured_inputs.get("messages", [])
        assert len(msgs) == 1
        assert _RUN_ID in msgs[0].content

    @pytest.mark.asyncio
    async def test_publishes_synthesis_phase_start(self):
        """Verifies START message uses Phase.SYNTHESIS."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={"messages": []})

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch("swarm_reasoning.agents.langgraph_base.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = SynthesizerHandler()
            await handler.run(_make_input())

        # First publish call should be the START message
        start_call = stream_mock.publish.call_args_list[0]
        start_msg = start_call[0][1]
        assert isinstance(start_msg, StartMessage)
        assert start_msg.phase == Phase.SYNTHESIS
        assert start_msg.agent == "synthesizer"

    @pytest.mark.asyncio
    async def test_syncs_observation_count(self):
        """Verifies AgentContext.seq_counter syncs to FanoutBase._seq."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        async def fake_ainvoke(inputs, config=None):
            ctx = config["context"]
            # Simulate tools publishing 4 observations (one per tool)
            for _ in range(4):
                ctx.next_seq()
            return {"messages": []}

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch("swarm_reasoning.agents.langgraph_base.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = SynthesizerHandler()
            result = await handler.run(_make_input())

        assert result.observation_count == 4

    @pytest.mark.asyncio
    async def test_skips_upstream_context_loading(self):
        """Verifies _load_upstream_context returns empty context."""
        handler = SynthesizerHandler()
        stream_mock = _make_stream_mock()
        ctx = await handler._load_upstream_context(stream_mock, _RUN_ID)
        assert ctx.normalized_claim == ""
        # Synthesizer should NOT read upstream streams — it uses resolve_observations
        stream_mock.read_range.assert_not_called()
