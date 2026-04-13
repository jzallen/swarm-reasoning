"""Unit tests for ClaimReview matcher agent (LangGraphBase conversion)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.claimreview_matcher.handler import ClaimReviewMatcherHandler
from swarm_reasoning.agents.claimreview_matcher.scorer import cosine_similarity
from swarm_reasoning.agents.evidence.tools import search_factchecks
from swarm_reasoning.agents.langgraph_base import LangGraphBase
from swarm_reasoning.agents.observation_tools import publish_progress
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode

# ---- Scorer tests (unchanged) ----


class TestCosineScorer:
    def test_identical_texts_score_high(self):
        score = cosine_similarity(
            "unemployment rate fell to 3.4%",
            "unemployment rate fell to 3.4%",
        )
        assert score >= 0.99

    def test_similar_texts_score_above_threshold(self):
        score = cosine_similarity(
            "the unemployment rate fell to 3.4% in January 2023",
            "unemployment rate dropped to 3.4 percent in January of 2023",
        )
        assert score >= 0.50

    def test_unrelated_texts_score_low(self):
        score = cosine_similarity(
            "the unemployment rate fell to 3.4%",
            "cats prefer to sleep in warm sunny spots",
        )
        assert score < 0.30

    def test_empty_texts_score_zero(self):
        assert cosine_similarity("", "hello world") == 0.0
        assert cosine_similarity("hello world", "") == 0.0


# ---- Handler tests (LangGraphBase) ----


def _mock_upstream_streams() -> dict[str, list]:
    from tests.unit.agents.test_fanout_base import _mock_upstream_streams
    return _mock_upstream_streams(
        normalized_claim="unemployment rate fell to 3.4% in January 2023",
        persons=["Joe Biden"],
    )


def _make_stream_mock(streams: dict[str, list]) -> AsyncMock:
    stream_mock = AsyncMock()

    async def read_range(key, **kwargs):
        return streams.get(key, [])

    stream_mock.read_range = AsyncMock(side_effect=read_range)
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()
    return stream_mock


def _make_input() -> MagicMock:
    inp = MagicMock()
    inp.run_id = "run-001"
    inp.agent_name = "claimreview-matcher"
    inp.claim_text = "Test claim"
    return inp


class TestHandlerStructure:
    """Verify the handler extends LangGraphBase correctly."""

    def test_extends_langgraph_base(self):
        assert issubclass(ClaimReviewMatcherHandler, LangGraphBase)

    def test_agent_name(self):
        handler = ClaimReviewMatcherHandler()
        assert handler.AGENT_NAME == "claimreview-matcher"

    def test_tools_includes_search_factchecks(self):
        handler = ClaimReviewMatcherHandler()
        tools = handler._tools()
        tool_names = [t.name for t in tools]
        assert "search_factchecks" in tool_names

    def test_tools_includes_publish_progress(self):
        handler = ClaimReviewMatcherHandler()
        tools = handler._tools()
        tool_names = [t.name for t in tools]
        assert "publish_progress" in tool_names

    def test_primary_code(self):
        handler = ClaimReviewMatcherHandler()
        assert handler._primary_code() == ObservationCode.CLAIMREVIEW_MATCH

    def test_system_prompt_is_string(self):
        handler = ClaimReviewMatcherHandler()
        prompt = handler._system_prompt()
        assert isinstance(prompt, str)
        assert "search_factchecks" in prompt


class TestHandlerExecution:
    """Verify the handler runs through LangGraphBase._execute correctly."""

    @pytest.mark.asyncio
    async def test_creates_react_agent_with_tools(self):
        """Verifies search_factchecks is passed to create_react_agent."""
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
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
            handler = ClaimReviewMatcherHandler()
            await handler.run(_make_input())

        assert captured_kwargs["context_schema"] is AgentContext
        tool_names = [t.name for t in captured_kwargs["tools"]]
        assert "search_factchecks" in tool_names
        assert "publish_progress" in tool_names

    @pytest.mark.asyncio
    async def test_passes_claim_context_to_agent(self):
        """Verifies claim context is formatted and sent as HumanMessage."""
        streams = _mock_upstream_streams()
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
            patch("swarm_reasoning.agents.langgraph_base.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = ClaimReviewMatcherHandler()
            await handler.run(_make_input())

        msgs = captured_inputs.get("messages", [])
        assert len(msgs) == 1
        assert "unemployment rate fell to 3.4%" in msgs[0].content
        assert "Joe Biden" in msgs[0].content

    @pytest.mark.asyncio
    async def test_syncs_observation_count(self):
        """Verifies AgentContext.seq_counter syncs to FanoutBase._seq."""
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        async def fake_ainvoke(inputs, config=None):
            ctx = config["context"]
            # Simulate search_factchecks publishing 5 observations
            for _ in range(5):
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
            handler = ClaimReviewMatcherHandler()
            result = await handler.run(_make_input())

        assert result.observation_count == 5
