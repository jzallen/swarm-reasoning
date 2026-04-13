"""Integration tests for blindspot-detector agent full flow (LangGraphBase)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.blindspot_detector.handler import (
    BlindspotDetectorHandler,
)
from swarm_reasoning.agents.langgraph_base import LangGraphBase
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.models.stream import ObsMessage, StopMessage

# Shorthand aliases for long observation codes
_SCORE = ObservationCode.BLINDSPOT_SCORE
_DIR = ObservationCode.BLINDSPOT_DIRECTION
_CORR = ObservationCode.CROSS_SPECTRUM_CORROBORATION


def _make_input(cross_agent_data: dict | None = None) -> MagicMock:
    inp = MagicMock()
    inp.run_id = "run-bs-001"
    inp.agent_name = "blindspot-detector"
    inp.claim_text = "Test claim"
    inp.cross_agent_data = cross_agent_data
    return inp


def _make_stream_mock() -> AsyncMock:
    stream_mock = AsyncMock()
    stream_mock.read_range = AsyncMock(return_value=[])
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()
    return stream_mock


def _full_coverage_data(
    left_count: int = 12,
    left_framing: str = "SUPPORTIVE",
    center_count: int = 7,
    center_framing: str = "NEUTRAL",
    right_count: int = 3,
    right_framing: str = "CRITICAL",
    convergence: float | None = 0.35,
) -> dict:
    data: dict = {
        "coverage": {
            "left": {
                "article_count": left_count,
                "framing": left_framing,
            },
            "center": {
                "article_count": center_count,
                "framing": center_framing,
            },
            "right": {
                "article_count": right_count,
                "framing": right_framing,
            },
        },
    }
    if convergence is not None:
        data["source_convergence_score"] = convergence
    return data


def _collect_obs(stream_mock: AsyncMock) -> list[ObsMessage]:
    """Extract all ObsMessage instances from stream publish calls."""
    return [
        call[0][1]
        for call in stream_mock.publish.call_args_list
        if isinstance(call[0][1], ObsMessage)
    ]


def _obs_by_code(observations: list[ObsMessage], code: ObservationCode) -> list[ObsMessage]:
    """Filter observations by code."""
    return [o for o in observations if o.observation.code == code]


class TestBlindspotDetectorStructure:
    """Verify the handler extends LangGraphBase correctly."""

    def test_extends_langgraph_base(self):
        assert issubclass(BlindspotDetectorHandler, LangGraphBase)

    def test_agent_name(self):
        handler = BlindspotDetectorHandler()
        assert handler.AGENT_NAME == "blindspot-detector"

    def test_tools_includes_analyze_blindspots(self):
        handler = BlindspotDetectorHandler()
        tools = handler._tools()
        tool_names = [t.name for t in tools]
        assert "analyze_blindspots" in tool_names

    def test_tools_includes_publish_progress(self):
        handler = BlindspotDetectorHandler()
        tools = handler._tools()
        tool_names = [t.name for t in tools]
        assert "publish_progress" in tool_names

    def test_primary_code(self):
        handler = BlindspotDetectorHandler()
        assert handler._primary_code() == _SCORE

    def test_system_prompt_mentions_blindspots(self):
        handler = BlindspotDetectorHandler()
        prompt = handler._system_prompt()
        assert "blindspot" in prompt.lower()
        assert "analyze_blindspots" in prompt


class TestBlindspotDetectorExecution:
    """Verify the handler passes coverage data to the LangGraph agent."""

    @pytest.mark.asyncio
    async def test_passes_coverage_data_as_message(self):
        """Verifies cross_agent_data is formatted into the HumanMessage."""
        cross_data = _full_coverage_data(right_count=0, right_framing="ABSENT")
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
            patch("swarm_reasoning.agents.blindspot_detector.handler.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = BlindspotDetectorHandler()
            await handler.run(_make_input(cross_data))

        msgs = captured_inputs.get("messages", [])
        assert len(msgs) == 1
        assert "coverage" in msgs[0].content
        assert "ABSENT" in msgs[0].content

    @pytest.mark.asyncio
    async def test_creates_react_agent_with_tools(self):
        """Verifies analyze_blindspots is passed to create_react_agent."""
        cross_data = _full_coverage_data()
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
            patch("swarm_reasoning.agents.blindspot_detector.handler.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                side_effect=fake_create,
            ),
        ):
            handler = BlindspotDetectorHandler()
            await handler.run(_make_input(cross_data))

        assert captured_kwargs["context_schema"] is AgentContext
        tool_names = [t.name for t in captured_kwargs["tools"]]
        assert "analyze_blindspots" in tool_names
        assert "publish_progress" in tool_names

    @pytest.mark.asyncio
    async def test_syncs_observation_count(self):
        """Verifies AgentContext.seq_counter syncs to FanoutBase._seq."""
        cross_data = _full_coverage_data()
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        async def fake_ainvoke(inputs, config=None):
            ctx = config["context"]
            # Simulate analyze_blindspots publishing 3 observations
            for _ in range(3):
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
            patch("swarm_reasoning.agents.blindspot_detector.handler.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = BlindspotDetectorHandler()
            result = await handler.run(_make_input(cross_data))

        assert result.observation_count == 3

    @pytest.mark.asyncio
    async def test_empty_cross_agent_data_handled(self):
        """Verifies handler handles None cross_agent_data gracefully."""
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
            patch("swarm_reasoning.agents.blindspot_detector.handler.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = BlindspotDetectorHandler()
            await handler.run(_make_input(None))

        msgs = captured_inputs.get("messages", [])
        assert len(msgs) == 1
        # Empty dict should be serialized as "{}"
        assert "{}" in msgs[0].content
