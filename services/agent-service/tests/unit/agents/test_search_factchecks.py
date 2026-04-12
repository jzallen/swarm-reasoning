"""Unit tests for search_factchecks @tool (match/no-match/error paths)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.evidence.tools import (
    _build_query,
    _score_matches,
    search_factchecks,
)
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage


def _make_context(agent_name: str = "claimreview-matcher", run_id: str = "run-001") -> AgentContext:
    """Create an AgentContext with mocked stream and Redis client."""
    stream = AsyncMock()
    stream.publish = AsyncMock()
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock()

    return AgentContext(
        stream=stream,
        redis_client=redis_client,
        run_id=run_id,
        sk=f"reasoning:{run_id}:{agent_name}",
        agent_name=agent_name,
    )


def _api_match_response() -> dict:
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


def _api_no_match_response() -> dict:
    return {"claims": []}


def _api_low_score_response() -> dict:
    """API response with a result that won't pass the similarity threshold."""
    return {
        "claims": [
            {
                "text": "cats prefer to sleep in warm sunny spots",
                "claimReview": [
                    {
                        "title": "cats prefer to sleep in warm sunny spots",
                        "publisher": {"name": "FactChecker"},
                        "textualRating": "True",
                        "url": "https://example.com/cats",
                    }
                ],
            }
        ]
    }


# ---- Query building ----


class TestBuildQuery:
    def test_combines_entities_and_claim(self):
        query = _build_query(
            "unemployment rate fell to 3.4%",
            persons=["Joe Biden"],
            organizations=[],
        )
        assert "Joe Biden" in query
        assert "unemployment" in query

    def test_truncates_to_100_chars(self):
        query = _build_query("x " * 100, persons=[], organizations=[])
        assert len(query) <= 100

    def test_includes_organizations(self):
        query = _build_query(
            "revenue increased",
            persons=[],
            organizations=["Acme Corp"],
        )
        assert "Acme Corp" in query

    def test_limits_to_two_entities(self):
        query = _build_query(
            "claim",
            persons=["A", "B", "C"],
            organizations=["D"],
        )
        assert "A" in query
        assert "B" in query
        assert "C" not in query


# ---- Score matches ----


class TestScoreMatches:
    def test_identical_claim_scores_high(self):
        results = [
            {
                "text": "unemployment rate fell to 3.4%",
                "claimReview": [{"title": "unemployment rate fell to 3.4%"}],
            }
        ]
        match, score = _score_matches(results, "unemployment rate fell to 3.4%")
        assert score >= 0.99
        assert match is results[0]

    def test_picks_best_match(self):
        results = [
            {
                "text": "cats sleep in sunny spots",
                "claimReview": [{"title": "cats sleep in sunny spots"}],
            },
            {
                "text": "unemployment rate fell to 3.4%",
                "claimReview": [{"title": "unemployment rate fell to 3.4%"}],
            },
        ]
        match, score = _score_matches(results, "unemployment rate fell to 3.4%")
        assert match is results[1]
        assert score >= 0.99


# ---- Tool: match path ----


class TestSearchFactchecksMatch:
    @pytest.mark.asyncio
    async def test_match_publishes_5_observations(self):
        ctx = _make_context()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _api_match_response()

        with (
            patch.dict(
                "os.environ",
                {"GOOGLE_FACTCHECK_API_KEY": "test-key"},
                clear=False,
            ),
            patch("swarm_reasoning.agents.evidence.tools.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await search_factchecks.ainvoke(
                {
                    "claim": "unemployment rate fell to 3.4% in January 2023",
                    "persons": ["Joe Biden"],
                    "context": ctx,
                }
            )

        assert "Match found" in result
        assert "PolitiFact" in result

        # 5 observations published via context
        assert ctx.stream.publish.await_count == 5
        assert ctx.seq_counter == 5

        calls = ctx.stream.publish.call_args_list
        obs_codes = [call[0][1].observation.code for call in calls]
        assert obs_codes == [
            ObservationCode.CLAIMREVIEW_MATCH,
            ObservationCode.CLAIMREVIEW_VERDICT,
            ObservationCode.CLAIMREVIEW_SOURCE,
            ObservationCode.CLAIMREVIEW_URL,
            ObservationCode.CLAIMREVIEW_MATCH_SCORE,
        ]

    @pytest.mark.asyncio
    async def test_match_observation_values(self):
        ctx = _make_context()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _api_match_response()

        with (
            patch.dict(
                "os.environ",
                {"GOOGLE_FACTCHECK_API_KEY": "test-key"},
                clear=False,
            ),
            patch("swarm_reasoning.agents.evidence.tools.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await search_factchecks.ainvoke(
                {
                    "claim": "unemployment rate fell to 3.4% in January 2023",
                    "context": ctx,
                }
            )

        calls = ctx.stream.publish.call_args_list

        # CLAIMREVIEW_MATCH value
        match_obs: ObsMessage = calls[0][0][1]
        assert match_obs.observation.value == "TRUE^Match Found^FCK"
        assert match_obs.observation.value_type == ValueType.CWE
        assert match_obs.observation.status == "F"

        # CLAIMREVIEW_VERDICT
        verdict_obs: ObsMessage = calls[1][0][1]
        assert "TRUE^True^POLITIFACT" in verdict_obs.observation.value
        assert verdict_obs.observation.value_type == ValueType.CWE

        # CLAIMREVIEW_SOURCE
        source_obs: ObsMessage = calls[2][0][1]
        assert source_obs.observation.value == "PolitiFact"
        assert source_obs.observation.value_type == ValueType.ST

        # CLAIMREVIEW_URL
        url_obs: ObsMessage = calls[3][0][1]
        assert url_obs.observation.value == "https://politifact.com/example"

        # CLAIMREVIEW_MATCH_SCORE
        score_obs: ObsMessage = calls[4][0][1]
        assert float(score_obs.observation.value) >= 0.50
        assert score_obs.observation.value_type == ValueType.NM
        assert score_obs.observation.units == "score"
        assert score_obs.observation.reference_range == "0.0-1.0"


# ---- Tool: no-match path ----


class TestSearchFactchecksNoMatch:
    @pytest.mark.asyncio
    async def test_empty_results_publishes_2_observations(self):
        ctx = _make_context()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _api_no_match_response()

        with (
            patch.dict(
                "os.environ",
                {"GOOGLE_FACTCHECK_API_KEY": "test-key"},
                clear=False,
            ),
            patch("swarm_reasoning.agents.evidence.tools.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await search_factchecks.ainvoke(
                {
                    "claim": "some claim with no matches",
                    "context": ctx,
                }
            )

        assert "No matching fact-checks found" in result
        assert ctx.stream.publish.await_count == 2
        assert ctx.seq_counter == 2

        calls = ctx.stream.publish.call_args_list
        match_obs: ObsMessage = calls[0][0][1]
        assert match_obs.observation.code == ObservationCode.CLAIMREVIEW_MATCH
        assert "FALSE" in match_obs.observation.value
        assert match_obs.observation.status == "F"

        score_obs: ObsMessage = calls[1][0][1]
        assert score_obs.observation.code == ObservationCode.CLAIMREVIEW_MATCH_SCORE
        assert score_obs.observation.value == "0.0"

    @pytest.mark.asyncio
    async def test_below_threshold_publishes_2_observations(self):
        ctx = _make_context()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _api_low_score_response()

        with (
            patch.dict(
                "os.environ",
                {"GOOGLE_FACTCHECK_API_KEY": "test-key"},
                clear=False,
            ),
            patch("swarm_reasoning.agents.evidence.tools.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await search_factchecks.ainvoke(
                {
                    "claim": "unemployment rate fell to 3.4%",
                    "context": ctx,
                }
            )

        assert "below similarity threshold" in result
        assert ctx.stream.publish.await_count == 2


# ---- Tool: error path ----


class TestSearchFactchecksError:
    @pytest.mark.asyncio
    async def test_missing_api_key_publishes_x_status(self):
        ctx = _make_context()

        with patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": ""}, clear=False):
            result = await search_factchecks.ainvoke(
                {
                    "claim": "any claim",
                    "context": ctx,
                }
            )

        assert "Error" in result
        assert ctx.stream.publish.await_count == 2

        calls = ctx.stream.publish.call_args_list
        for call in calls:
            obs: ObsMessage = call[0][1]
            assert obs.observation.status == "X"

    @pytest.mark.asyncio
    async def test_api_error_publishes_x_status(self):
        ctx = _make_context()

        with (
            patch.dict(
                "os.environ",
                {"GOOGLE_FACTCHECK_API_KEY": "test-key"},
                clear=False,
            ),
            patch("swarm_reasoning.agents.evidence.tools.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await search_factchecks.ainvoke(
                {
                    "claim": "any claim",
                    "context": ctx,
                }
            )

        assert "Error" in result
        assert ctx.stream.publish.await_count == 2

        calls = ctx.stream.publish.call_args_list
        for call in calls:
            obs: ObsMessage = call[0][1]
            assert obs.observation.status == "X"

        # Verify note captures error detail
        match_obs: ObsMessage = calls[0][0][1]
        assert match_obs.observation.note is not None
        assert "API error" in match_obs.observation.note

    @pytest.mark.asyncio
    async def test_no_persons_or_orgs_defaults_to_empty(self):
        """Verify the tool works when optional entity lists are omitted."""
        ctx = _make_context()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _api_no_match_response()

        with (
            patch.dict(
                "os.environ",
                {"GOOGLE_FACTCHECK_API_KEY": "test-key"},
                clear=False,
            ),
            patch("swarm_reasoning.agents.evidence.tools.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # Omit persons and organizations entirely
            result = await search_factchecks.ainvoke(
                {
                    "claim": "some claim",
                    "context": ctx,
                }
            )

        assert "No matching fact-checks found" in result


# Need httpx for ConnectError in the error test
import httpx  # noqa: E402
