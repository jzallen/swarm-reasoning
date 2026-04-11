"""Unit tests for ClaimReview matcher agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.claimreview_matcher.handler import (
    ClaimReviewMatcherHandler,
    _build_query,
)
from swarm_reasoning.agents.claimreview_matcher.scorer import cosine_similarity
from swarm_reasoning.agents.fanout_base import ClaimContext
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage, StartMessage, StopMessage


# ---- Scorer tests ----


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


# ---- Query building tests ----


class TestBuildQuery:
    def test_combines_entities_and_claim(self):
        ctx = ClaimContext(
            normalized_claim="unemployment rate fell to 3.4% in january 2023",
            persons=["Joe Biden"],
        )
        query = _build_query(ctx)
        assert "Joe Biden" in query
        assert "unemployment" in query

    def test_truncates_to_100_chars(self):
        ctx = ClaimContext(normalized_claim="x " * 100)
        query = _build_query(ctx)
        assert len(query) <= 100


# ---- Handler tests ----


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


def _mock_api_match_response() -> dict:
    """API response with a matching ClaimReview."""
    return {
        "claims": [
            {
                "text": "unemployment rate fell to 3.4% in January 2023",
                "claimReview": [
                    {
                        "title": "unemployment rate fell to 3.4% in January 2023",
                        "publisher": {"name": "PolitiFact"},
                        "textualRating": "True",
                        "url": "https://politifact.com/example",
                    }
                ],
            }
        ]
    }


def _mock_api_no_match_response() -> dict:
    return {"claims": []}


class TestClaimReviewMatchPath:
    @pytest.mark.asyncio
    async def test_match_publishes_5_observations(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_api_match_response()

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
            patch("swarm_reasoning.agents.claimreview_matcher.handler.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            handler = ClaimReviewMatcherHandler()
            handler._api_key = "test-key"
            result = await handler.run(_make_input())

        assert result.terminal_status == "F"
        # START + 5 OBS + STOP = 7
        assert result.observation_count == 5

        calls = stream_mock.publish.call_args_list
        assert len(calls) == 7

        # Verify observation codes in order
        obs_codes = []
        for call in calls:
            msg = call[0][1]
            if isinstance(msg, ObsMessage):
                obs_codes.append(msg.observation.code)

        assert obs_codes == [
            ObservationCode.CLAIMREVIEW_MATCH,
            ObservationCode.CLAIMREVIEW_VERDICT,
            ObservationCode.CLAIMREVIEW_SOURCE,
            ObservationCode.CLAIMREVIEW_URL,
            ObservationCode.CLAIMREVIEW_MATCH_SCORE,
        ]


class TestClaimReviewNoMatch:
    @pytest.mark.asyncio
    async def test_no_match_publishes_2_observations(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_api_no_match_response()

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
            patch("swarm_reasoning.agents.claimreview_matcher.handler.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            handler = ClaimReviewMatcherHandler()
            handler._api_key = "test-key"
            result = await handler.run(_make_input())

        assert result.terminal_status == "F"
        assert result.observation_count == 2

        # Check CLAIMREVIEW_MATCH is FALSE
        calls = stream_mock.publish.call_args_list
        match_obs = None
        for call in calls:
            msg = call[0][1]
            if isinstance(msg, ObsMessage) and msg.observation.code == ObservationCode.CLAIMREVIEW_MATCH:
                match_obs = msg.observation
                break
        assert match_obs is not None
        assert "FALSE" in match_obs.value


class TestClaimReviewApiError:
    @pytest.mark.asyncio
    async def test_missing_api_key_publishes_x_status(self):
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
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": ""}, clear=False),
        ):
            handler = ClaimReviewMatcherHandler()
            handler._api_key = ""
            result = await handler.run(_make_input())

        # X-status observations from error path, but lifecycle completes F
        # (error is graceful, not a crash)
        calls = stream_mock.publish.call_args_list
        x_obs = [
            c[0][1] for c in calls
            if isinstance(c[0][1], ObsMessage) and c[0][1].observation.status == "X"
        ]
        assert len(x_obs) == 2
