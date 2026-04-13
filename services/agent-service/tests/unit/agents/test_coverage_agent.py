"""Unit tests for coverage agents (left, center, right)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.coverage_core import (
    build_search_query,
    classify_framing,
    compute_compound_sentiment,
    select_top_source,
)
from swarm_reasoning.agents.coverage_left.handler import CoverageLeftHandler
from swarm_reasoning.agents.fanout_base import ClaimContext
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.models.stream import ObsMessage, StopMessage

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


# ---- Handler tests ----


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


def _mock_newsapi_response(article_count: int = 5) -> MagicMock:
    articles = []
    for i in range(article_count):
        articles.append({
            "source": {"id": "msnbc", "name": "MSNBC"},
            "title": f"Economy shows strong growth in latest report {i}",
            "url": f"https://msnbc.com/article-{i}",
        })
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"articles": articles}
    return resp


class TestCoverageArticlesFound:
    @pytest.mark.asyncio
    async def test_publishes_4_observations(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_resp = _mock_newsapi_response(5)

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
            patch("swarm_reasoning.agents.coverage_core_tools.httpx.AsyncClient") as mock_client_cls,
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch(
                "swarm_reasoning.agents.coverage_core.load_sources",
                return_value=[
                    {"id": "msnbc", "name": "MSNBC", "credibility_rank": 60},
                    {"id": "huffington-post", "name": "HuffPost", "credibility_rank": 65},
                ],
            ),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            handler = CoverageLeftHandler()
            handler._sources = [
                {"id": "msnbc", "name": "MSNBC", "credibility_rank": 60},
                {"id": "huffington-post", "name": "HuffPost", "credibility_rank": 65},
            ]
            result = await handler.run(_make_input())

        assert result.terminal_status == "F"
        assert result.observation_count == 4

        # Verify observation codes
        obs_codes = []
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if isinstance(msg, ObsMessage):
                obs_codes.append(msg.observation.code)

        assert obs_codes == [
            ObservationCode.COVERAGE_ARTICLE_COUNT,
            ObservationCode.COVERAGE_FRAMING,
            ObservationCode.COVERAGE_TOP_SOURCE,
            ObservationCode.COVERAGE_TOP_SOURCE_URL,
        ]


class TestCoverageNoArticles:
    @pytest.mark.asyncio
    async def test_publishes_2_observations_when_empty(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_resp = _mock_newsapi_response(0)

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
            patch("swarm_reasoning.agents.coverage_core_tools.httpx.AsyncClient") as mock_client_cls,
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            handler = CoverageLeftHandler()
            handler._sources = [{"id": "msnbc", "name": "MSNBC", "credibility_rank": 60}]
            result = await handler.run(_make_input())

        assert result.terminal_status == "F"
        assert result.observation_count == 2

        # Check COVERAGE_FRAMING is ABSENT
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if (
                isinstance(msg, ObsMessage)
                and msg.observation.code == ObservationCode.COVERAGE_FRAMING
            ):
                assert "ABSENT" in msg.observation.value

        # STOP has F status (empty coverage is valid)
        stop_calls = [
            c[0][1] for c in stream_mock.publish.call_args_list
            if isinstance(c[0][1], StopMessage)
        ]
        assert len(stop_calls) == 1
        assert stop_calls[0].final_status == "F"
        assert stop_calls[0].observation_count == 2


class TestCoverageApiError:
    @pytest.mark.asyncio
    async def test_missing_api_key_produces_x_status_obs(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

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
            patch.dict("os.environ", {}, clear=True),
        ):
            handler = CoverageLeftHandler()
            handler._sources = [{"id": "msnbc", "name": "MSNBC", "credibility_rank": 60}]
            await handler.run(_make_input())

        # Error observations should have X status
        x_obs = [
            c[0][1] for c in stream_mock.publish.call_args_list
            if isinstance(c[0][1], ObsMessage) and c[0][1].observation.status == "X"
        ]
        assert len(x_obs) == 2
