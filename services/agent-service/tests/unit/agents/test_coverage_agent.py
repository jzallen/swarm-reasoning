"""Unit tests for coverage agents (left, center, right).

Tests cover:
  - Pure utility functions (build_search_query, sentiment, framing, source selection)
  - LangGraphBase handler structure (tools, prompt, primary code)
  - LangGraphBase handler execution (agent creation, source injection, seq sync)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.coverage.core import (
    CoverageHandler,
    build_search_query,
    classify_framing,
    compute_compound_sentiment,
    select_top_source,
)
from swarm_reasoning.agents.coverage.handlers import (
    CoverageLeftHandler,
    CoverageCenterHandler,
    CoverageRightHandler,
)
from swarm_reasoning.agents.fanout_base import ClaimContext
from swarm_reasoning.agents.langgraph_base import LangGraphBase
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode

# ---- Utility tests ----


class TestBuildSearchQuery:
    def test_removes_stop_words(self):
        ctx = ClaimContext(
            normalized_claim="the unemployment rate fell to 3.4% in january 2023"
        )
        query = build_search_query(ctx)
        assert "the" not in query.split()
        assert "unemployment" in query
        assert "3.4%" in query

    def test_truncates_to_100_chars(self):
        ctx = ClaimContext(normalized_claim="word " * 100)
        query = build_search_query(ctx)
        assert len(query) <= 100

    def test_truncates_at_word_boundary(self):
        ctx = ClaimContext(normalized_claim="word " * 100)
        query = build_search_query(ctx)
        assert not query.endswith(" ")


class TestSentimentScoring:
    def test_positive_headlines(self):
        headlines = [
            "Economy shows strong growth as unemployment falls",
            "Record gains in employment boost confidence",
            "Positive economic recovery continues",
        ]
        score = compute_compound_sentiment(headlines)
        assert score > 0.05

    def test_negative_headlines(self):
        headlines = [
            "Crisis deepens as losses mount in economy",
            "Failed policies lead to dangerous decline",
            "Fears of collapse grow amid weakness",
        ]
        score = compute_compound_sentiment(headlines)
        assert score < -0.05

    def test_neutral_headlines(self):
        headlines = [
            "Officials discuss employment statistics",
            "Report examines labor market trends",
        ]
        score = compute_compound_sentiment(headlines)
        assert -0.05 < score < 0.05

    def test_empty_headlines(self):
        assert compute_compound_sentiment([]) == 0.0

    def test_negation_flips_sentiment(self):
        positive = compute_compound_sentiment(["Economy gains strong growth"])
        negated = compute_compound_sentiment(["Economy not gains not strong growth"])
        # Negation should push score negative relative to positive
        assert negated < positive


class TestFramingClassification:
    def test_supportive(self):
        assert classify_framing(0.3) == "SUPPORTIVE^Supportive^FCK"

    def test_critical(self):
        assert classify_framing(-0.3) == "CRITICAL^Critical^FCK"

    def test_neutral(self):
        assert classify_framing(0.0) == "NEUTRAL^Neutral^FCK"

    def test_boundary_positive(self):
        assert classify_framing(0.05) == "SUPPORTIVE^Supportive^FCK"

    def test_boundary_negative(self):
        assert classify_framing(-0.05) == "CRITICAL^Critical^FCK"


class TestTopSourceSelection:
    def test_selects_highest_ranked(self):
        articles = [
            {"source": {"id": "reuters", "name": "Reuters"}, "url": "https://reuters.com/a"},
            {"source": {"id": "the-hill", "name": "The Hill"}, "url": "https://thehill.com/a"},
        ]
        sources = [
            {"id": "reuters", "name": "Reuters", "credibility_rank": 95},
            {"id": "the-hill", "name": "The Hill", "credibility_rank": 72},
        ]
        result = select_top_source(articles, sources)
        assert result is not None
        name, url = result
        assert name == "Reuters"
        assert url == "https://reuters.com/a"

    def test_empty_articles_returns_none(self):
        assert select_top_source([], []) is None

    def test_single_article(self):
        articles = [
            {"source": {"id": "bloomberg", "name": "Bloomberg"}, "url": "https://bloomberg.com/a"},
        ]
        sources = [
            {"id": "bloomberg", "name": "Bloomberg", "credibility_rank": 90},
        ]
        result = select_top_source(articles, sources)
        assert result is not None
        assert result[0] == "Bloomberg"


# ---- Handler structure tests ----


def _mock_upstream_streams() -> dict[str, list]:
    from tests.unit.agents.test_fanout_base import _mock_upstream_streams
    return _mock_upstream_streams(
        normalized_claim="unemployment rate fell to 3.4% in January 2023"
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
    inp.agent_name = "coverage-left"
    inp.claim_text = "Test claim"
    return inp


class TestHandlerStructure:
    """Verify coverage handlers extend LangGraphBase correctly."""

    def test_extends_langgraph_base(self):
        assert issubclass(CoverageHandler, LangGraphBase)
        assert issubclass(CoverageLeftHandler, LangGraphBase)
        assert issubclass(CoverageCenterHandler, LangGraphBase)
        assert issubclass(CoverageRightHandler, LangGraphBase)

    def test_agent_names(self):
        assert CoverageLeftHandler().AGENT_NAME == "coverage-left"
        assert CoverageCenterHandler().AGENT_NAME == "coverage-center"
        assert CoverageRightHandler().AGENT_NAME == "coverage-right"

    def test_spectrum_labels(self):
        assert CoverageLeftHandler().SPECTRUM == "left"
        assert CoverageCenterHandler().SPECTRUM == "center"
        assert CoverageRightHandler().SPECTRUM == "right"

    def test_tools_includes_coverage_tools(self):
        handler = CoverageLeftHandler()
        tools = handler._tools()
        tool_names = [t.name for t in tools]
        assert "build_coverage_query" in tool_names
        assert "search_coverage" in tool_names
        assert "detect_coverage_framing" in tool_names
        assert "find_top_coverage_source" in tool_names

    def test_tools_includes_publish_progress(self):
        handler = CoverageLeftHandler()
        tools = handler._tools()
        tool_names = [t.name for t in tools]
        assert "publish_progress" in tool_names

    def test_primary_code(self):
        handler = CoverageLeftHandler()
        assert handler._primary_code() == ObservationCode.COVERAGE_ARTICLE_COUNT

    def test_system_prompt_contains_spectrum(self):
        for handler_cls, spectrum in [
            (CoverageLeftHandler, "left"),
            (CoverageCenterHandler, "center"),
            (CoverageRightHandler, "right"),
        ]:
            handler = handler_cls()
            prompt = handler._system_prompt()
            assert isinstance(prompt, str)
            assert spectrum in prompt

    def test_system_prompt_references_tools(self):
        handler = CoverageLeftHandler()
        prompt = handler._system_prompt()
        assert "build_coverage_query" in prompt
        assert "search_coverage" in prompt
        assert "detect_coverage_framing" in prompt
        assert "find_top_coverage_source" in prompt


# ---- Handler execution tests ----


class TestHandlerExecution:
    """Verify the handler runs through LangGraphBase._execute correctly."""

    @pytest.mark.asyncio
    async def test_creates_react_agent_with_tools(self):
        """Verifies coverage tools are passed to create_react_agent."""
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
            patch("langchain_anthropic.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                side_effect=fake_create,
            ),
        ):
            handler = CoverageLeftHandler()
            handler._sources = [
                {"id": "msnbc", "name": "MSNBC", "credibility_rank": 60},
            ]
            await handler.run(_make_input())

        assert captured_kwargs["context_schema"] is AgentContext
        tool_names = [t.name for t in captured_kwargs["tools"]]
        assert "build_coverage_query" in tool_names
        assert "search_coverage" in tool_names
        assert "detect_coverage_framing" in tool_names
        assert "find_top_coverage_source" in tool_names
        assert "publish_progress" in tool_names

    @pytest.mark.asyncio
    async def test_injects_source_data_in_message(self):
        """Verifies source IDs and sources JSON are included in the message."""
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
            patch("langchain_anthropic.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = CoverageLeftHandler()
            handler._sources = [
                {"id": "msnbc", "name": "MSNBC", "credibility_rank": 60},
                {"id": "huffington-post", "name": "HuffPost", "credibility_rank": 65},
            ]
            await handler.run(_make_input())

        msgs = captured_inputs.get("messages", [])
        assert len(msgs) == 1
        content = msgs[0].content
        # Claim context is included
        assert "unemployment rate fell to 3.4%" in content
        # Source IDs for search_coverage
        assert "msnbc" in content
        assert "huffington-post" in content
        # Sources JSON for find_top_coverage_source
        assert "MSNBC" in content
        assert "credibility_rank" in content

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
            # Simulate tools publishing 4 observations
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
            patch("langchain_anthropic.ChatAnthropic"),
            patch(
                "langgraph.prebuilt.create_react_agent",
                return_value=mock_graph,
            ),
        ):
            handler = CoverageLeftHandler()
            handler._sources = [
                {"id": "msnbc", "name": "MSNBC", "credibility_rank": 60},
            ]
            result = await handler.run(_make_input())

        assert result.observation_count == 4
