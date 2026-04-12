"""Unit tests for LangGraphBase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from swarm_reasoning.agents.fanout_base import ClaimContext
from swarm_reasoning.agents.langgraph_base import (
    DEFAULT_MODEL_ID,
    LangGraphBase,
    _format_claim_input,
)
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ConcreteLangGraph(LangGraphBase):
    """Minimal concrete subclass for testing."""

    AGENT_NAME = "test-langgraph"

    def _tools(self):
        return [MagicMock(name="dummy_tool")]

    def _system_prompt(self):
        return "You are a test agent."

    def _primary_code(self):
        return ObservationCode.CLAIMREVIEW_MATCH


class CustomModelLangGraph(ConcreteLangGraph):
    """Subclass that overrides _model_id."""

    def _model_id(self):
        return "claude-haiku-4-5-20251001"


def _mock_upstream_streams(
    normalized_claim: str = "unemployment rate fell to 3.4%",
    domain: str = "ECONOMICS",
) -> dict[str, list]:
    """Build minimal mock stream responses for Phase 1 agents."""
    from swarm_reasoning.models.observation import Observation, ValueType
    from swarm_reasoning.models.stream import ObsMessage

    detector = [
        MagicMock(type="START"),
        ObsMessage(
            observation=Observation(
                runId="run-001",
                agent="claim-detector",
                seq=1,
                code=ObservationCode.CLAIM_NORMALIZED,
                value=normalized_claim,
                valueType=ValueType.ST,
                status="F",
                timestamp="2026-04-10T12:00:00Z",
            )
        ),
        MagicMock(type="STOP"),
    ]
    ingestion = [
        MagicMock(type="START"),
        ObsMessage(
            observation=Observation(
                runId="run-001",
                agent="ingestion-agent",
                seq=1,
                code=ObservationCode.CLAIM_DOMAIN,
                value=domain,
                valueType=ValueType.ST,
                status="F",
                timestamp="2026-04-10T12:00:00Z",
            )
        ),
        MagicMock(type="STOP"),
    ]
    extractor = [MagicMock(type="START"), MagicMock(type="STOP")]

    return {
        "reasoning:run-001:claim-detector": detector,
        "reasoning:run-001:ingestion-agent": ingestion,
        "reasoning:run-001:entity-extractor": extractor,
    }


def _make_stream_mock(streams: dict[str, list]) -> AsyncMock:
    stream_mock = AsyncMock()

    async def read_range(key, **kwargs):
        return streams.get(key, [])

    stream_mock.read_range = AsyncMock(side_effect=read_range)
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()
    return stream_mock


def _make_input(run_id: str = "run-001") -> MagicMock:
    inp = MagicMock()
    inp.run_id = run_id
    inp.agent_name = "test-langgraph"
    inp.claim_text = "Test claim"
    return inp


# ---------------------------------------------------------------------------
# Tests: abstract interface
# ---------------------------------------------------------------------------


class TestAbstractInterface:
    def test_cannot_instantiate_base(self):
        with pytest.raises(TypeError):
            LangGraphBase()

    def test_concrete_subclass_instantiates(self):
        handler = ConcreteLangGraph()
        assert handler.AGENT_NAME == "test-langgraph"

    def test_tools_returns_list(self):
        handler = ConcreteLangGraph()
        tools = handler._tools()
        assert isinstance(tools, list)
        assert len(tools) == 1

    def test_system_prompt_returns_string(self):
        handler = ConcreteLangGraph()
        prompt = handler._system_prompt()
        assert isinstance(prompt, str)
        assert "test agent" in prompt

    def test_default_model_id(self):
        handler = ConcreteLangGraph()
        assert handler._model_id() == DEFAULT_MODEL_ID

    def test_custom_model_id(self):
        handler = CustomModelLangGraph()
        assert handler._model_id() == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Tests: _format_claim_input
# ---------------------------------------------------------------------------


class TestFormatClaimInput:
    def test_claim_only(self):
        ctx = ClaimContext(normalized_claim="Earth is round")
        result = _format_claim_input(ctx)
        assert result == "Claim: Earth is round"

    def test_with_domain(self):
        ctx = ClaimContext(normalized_claim="test", domain="HEALTHCARE")
        result = _format_claim_input(ctx)
        assert "Domain: HEALTHCARE" in result

    def test_other_domain_excluded(self):
        ctx = ClaimContext(normalized_claim="test", domain="OTHER")
        result = _format_claim_input(ctx)
        assert "Domain:" not in result

    def test_with_persons(self):
        ctx = ClaimContext(normalized_claim="test", persons=["Alice", "Bob"])
        result = _format_claim_input(ctx)
        assert "Persons: Alice, Bob" in result

    def test_with_organizations(self):
        ctx = ClaimContext(normalized_claim="test", organizations=["CDC", "WHO"])
        result = _format_claim_input(ctx)
        assert "Organizations: CDC, WHO" in result

    def test_with_dates(self):
        ctx = ClaimContext(normalized_claim="test", dates=["2024-01-01"])
        result = _format_claim_input(ctx)
        assert "Dates: 2024-01-01" in result

    def test_with_locations(self):
        ctx = ClaimContext(normalized_claim="test", locations=["Washington DC"])
        result = _format_claim_input(ctx)
        assert "Locations: Washington DC" in result

    def test_with_statistics(self):
        ctx = ClaimContext(normalized_claim="test", statistics=["3.4%"])
        result = _format_claim_input(ctx)
        assert "Statistics: 3.4%" in result

    def test_full_context(self):
        ctx = ClaimContext(
            normalized_claim="unemployment fell",
            domain="ECONOMICS",
            persons=["Biden"],
            organizations=["BLS"],
            dates=["2024-01"],
            locations=["USA"],
            statistics=["3.4%"],
        )
        result = _format_claim_input(ctx)
        lines = result.split("\n")
        assert len(lines) == 7
        assert lines[0] == "Claim: unemployment fell"

    def test_empty_lists_excluded(self):
        ctx = ClaimContext(normalized_claim="test", persons=[], organizations=[])
        result = _format_claim_input(ctx)
        assert "Persons:" not in result
        assert "Organizations:" not in result


# ---------------------------------------------------------------------------
# Tests: _execute integration with create_react_agent
# ---------------------------------------------------------------------------


class TestExecute:
    @pytest.mark.asyncio
    async def test_creates_agent_context(self):
        """AgentContext is created with correct fields and passed to graph."""
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        captured_config = {}

        async def fake_ainvoke(inputs, config=None):
            captured_config.update(config or {})
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
            patch(
                "swarm_reasoning.agents.langgraph_base.ChatAnthropic",
            ),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = ConcreteLangGraph()
            await handler.run(_make_input())

        ctx = captured_config.get("context")
        assert isinstance(ctx, AgentContext)
        assert ctx.agent_name == "test-langgraph"
        assert ctx.run_id == "run-001"
        assert ctx.sk == "reasoning:run-001:test-langgraph"

    @pytest.mark.asyncio
    async def test_passes_claim_as_human_message(self):
        """Claim context is formatted and sent as HumanMessage."""
        streams = _mock_upstream_streams(normalized_claim="test claim here")
        stream_mock = _make_stream_mock(streams)
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
            patch(
                "swarm_reasoning.agents.langgraph_base.ChatAnthropic",
            ),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = ConcreteLangGraph()
            await handler.run(_make_input())

        msgs = captured_inputs.get("messages", [])
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)
        assert "test claim here" in msgs[0].content

    @pytest.mark.asyncio
    async def test_appends_tool_usage_suffix_to_prompt(self):
        """TOOL_USAGE_SUFFIX is appended to the system prompt."""
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={"messages": []})

        captured_prompt = []

        def fake_create_react_agent(*, model, tools, prompt, context_schema):
            captured_prompt.append(prompt)
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
            patch(
                "swarm_reasoning.agents.langgraph_base.ChatAnthropic",
            ),
            patch(
                "langgraph.prebuilt.create_react_agent",
                side_effect=fake_create_react_agent,
            ),
        ):
            handler = ConcreteLangGraph()
            await handler.run(_make_input())

        from swarm_reasoning.agents.prompts import TOOL_USAGE_SUFFIX

        assert len(captured_prompt) == 1
        assert captured_prompt[0].startswith("You are a test agent.")
        assert captured_prompt[0].endswith(TOOL_USAGE_SUFFIX)

    @pytest.mark.asyncio
    async def test_syncs_seq_counter(self):
        """FanoutBase._seq is updated from AgentContext.seq_counter."""
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        async def fake_ainvoke(inputs, config=None):
            # Simulate tools publishing 3 observations
            ctx = config["context"]
            ctx.next_seq()
            ctx.next_seq()
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
            patch(
                "swarm_reasoning.agents.langgraph_base.ChatAnthropic",
            ),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = ConcreteLangGraph()
            result = await handler.run(_make_input())

        assert result.observation_count == 3

    @pytest.mark.asyncio
    async def test_uses_custom_model_id(self):
        """Custom _model_id() is passed to ChatAnthropic."""
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={"messages": []})

        mock_chat = MagicMock()

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
            patch(
                "swarm_reasoning.agents.langgraph_base.ChatAnthropic",
                return_value=mock_chat,
            ) as mock_cls,
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = CustomModelLangGraph()
            await handler.run(_make_input())

        mock_cls.assert_called_once_with(model="claude-haiku-4-5-20251001")

    @pytest.mark.asyncio
    async def test_passes_context_schema(self):
        """AgentContext is passed as context_schema to create_react_agent."""
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={"messages": []})

        captured_kwargs = {}

        def fake_create(*, model, tools, prompt, context_schema):
            captured_kwargs["context_schema"] = context_schema
            captured_kwargs["tools"] = tools
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
            handler = ConcreteLangGraph()
            await handler.run(_make_input())

        assert captured_kwargs["context_schema"] is AgentContext
        assert len(captured_kwargs["tools"]) == 1
