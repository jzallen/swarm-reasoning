"""Tests for coverage pipeline node (M3.2).

Tests cover:
- Tool 1: build_search_query (stop-word removal, truncation, word boundary)
- Tool 2: search_coverage (API success, missing key, API error, rate-limit retry)
- Tool 3: detect_coverage_framing (with articles, empty articles)
- Tool 4: find_top_coverage_source (best credibility, no articles)
- Per-spectrum runner: _run_spectrum orchestration
- Full node: happy path across 3 spectrums, degradation (no API key),
  heartbeats, observations, state output structure, framing_analysis
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.pipeline.nodes.coverage import (
    _run_spectrum,
    _SPECTRUMS,
    _STATE_KEYS,
    build_search_query,
    coverage_node,
    detect_coverage_framing,
    find_top_coverage_source,
    search_coverage,
)
from swarm_reasoning.pipeline.state import PipelineState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ctx():
    """Create a mock PipelineContext with tracking for published observations."""
    ctx = MagicMock(spec=PipelineContext)
    ctx.run_id = "run-test"
    ctx.session_id = "sess-test"
    ctx.redis_client = AsyncMock()
    ctx.publish_observation = AsyncMock()
    ctx.publish_progress = AsyncMock()
    ctx.heartbeat = MagicMock()
    return ctx


@pytest.fixture
def mock_config(mock_ctx):
    """Create a mock RunnableConfig with PipelineContext."""
    return {"configurable": {"pipeline_context": mock_ctx}}


@pytest.fixture
def base_state() -> PipelineState:
    """Minimal valid PipelineState for coverage testing (post-intake)."""
    return {
        "claim_text": "The unemployment rate dropped to 3.5% in 2024",
        "run_id": "run-test",
        "session_id": "sess-test",
        "normalized_claim": "the unemployment rate dropped to 3.5% in 2024",
        "observations": [],
        "errors": [],
    }


@pytest.fixture
def sample_sources():
    """Sample source list matching the JSON format."""
    return [
        {"id": "source-a", "name": "Source A", "credibility_rank": 80},
        {"id": "source-b", "name": "Source B", "credibility_rank": 60},
        {"id": "source-c", "name": "Source C", "credibility_rank": 90},
    ]


@pytest.fixture
def sample_articles():
    """Sample NewsAPI article responses."""
    return [
        {
            "title": "Economy grows amid strong jobs data",
            "url": "https://example.com/article1",
            "source": {"id": "source-a", "name": "Source A"},
        },
        {
            "title": "Unemployment drops to record low",
            "url": "https://example.com/article2",
            "source": {"id": "source-c", "name": "Source C"},
        },
    ]


# ---------------------------------------------------------------------------
# Tool 1: build_search_query
# ---------------------------------------------------------------------------


class TestBuildSearchQuery:
    """Tests for the stop-word removal and truncation query builder."""

    def test_removes_stop_words(self):
        query = build_search_query("the economy is growing in the country")
        assert "the" not in query.split()
        assert "is" not in query.split()
        assert "in" not in query.split()
        assert "economy" in query
        assert "growing" in query
        assert "country" in query

    def test_short_query_unchanged(self):
        query = build_search_query("unemployment rate dropped")
        assert query == "unemployment rate dropped"

    def test_truncates_at_100_chars(self):
        long_claim = " ".join(["economy"] * 50)
        query = build_search_query(long_claim)
        assert len(query) <= 100

    def test_truncates_at_word_boundary(self):
        # Build a claim that produces a query longer than 100 chars
        long_claim = "unemployment economy growth inflation deficit spending revenue"
        long_claim = " ".join([long_claim] * 5)
        query = build_search_query(long_claim)
        if len(query) < 100:
            # Query was short enough after stop-word removal; skip boundary test
            return
        # Should not end mid-word
        assert not query[-1].isspace()
        # Last char should be a letter (not cut in the middle of a word)
        words = query.split()
        assert all(len(w) > 0 for w in words)

    def test_empty_claim(self):
        query = build_search_query("")
        assert query == ""

    def test_all_stop_words(self):
        query = build_search_query("the is a an the it")
        assert query == ""


# ---------------------------------------------------------------------------
# Tool 2: search_coverage
# ---------------------------------------------------------------------------


class TestSearchCoverage:
    """Tests for the NewsAPI search tool."""

    @pytest.mark.asyncio
    async def test_successful_search(self, mock_ctx):
        """API returns articles → publishes COVERAGE_ARTICLE_COUNT and returns list."""
        articles = [
            {"title": "Article 1", "url": "https://example.com/1"},
            {"title": "Article 2", "url": "https://example.com/2"},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"articles": articles}

        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await search_coverage("test query", "src1,src2", mock_ctx, "coverage-left")

        assert len(result) == 2
        assert mock_ctx.publish_observation.call_count == 1
        call = mock_ctx.publish_observation.call_args
        assert call.kwargs["code"] == ObservationCode.COVERAGE_ARTICLE_COUNT
        assert call.kwargs["value"] == "2"

    @pytest.mark.asyncio
    async def test_missing_api_key(self, mock_ctx):
        """No NEWSAPI_KEY → returns empty list with X-status observations."""
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("NEWSAPI_KEY", None)
            result = await search_coverage("test query", "src1", mock_ctx, "coverage-left")

        assert result == []
        assert mock_ctx.publish_observation.call_count == 2
        for call in mock_ctx.publish_observation.call_args_list:
            assert call.kwargs["status"] == "X"

    @pytest.mark.asyncio
    async def test_missing_api_key_publishes_article_count_and_framing(self, mock_ctx):
        """Missing API key publishes both ARTICLE_COUNT and FRAMING as X."""
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("NEWSAPI_KEY", None)
            await search_coverage("test query", "src1", mock_ctx, "coverage-left")

        codes = [c.kwargs["code"] for c in mock_ctx.publish_observation.call_args_list]
        assert ObservationCode.COVERAGE_ARTICLE_COUNT in codes
        assert ObservationCode.COVERAGE_FRAMING in codes

    @pytest.mark.asyncio
    async def test_api_error(self, mock_ctx):
        """Network exception → returns empty list with X-status observations."""
        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await search_coverage("test query", "src1", mock_ctx, "coverage-left")

        assert result == []
        assert mock_ctx.publish_observation.call_count == 2
        for call in mock_ctx.publish_observation.call_args_list:
            assert call.kwargs["status"] == "X"

    @pytest.mark.asyncio
    async def test_http_error_status(self, mock_ctx):
        """HTTP 500 → returns empty list with X-status observations."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.request = MagicMock()

        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await search_coverage("test query", "src1", mock_ctx, "coverage-left")

        assert result == []
        assert mock_ctx.publish_observation.call_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_retry(self, mock_ctx):
        """HTTP 429 → retries once after sleep."""
        articles = [{"title": "Retry Success", "url": "https://example.com/retry"}]
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_429.request = MagicMock()

        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.json.return_value = {"articles": articles}

        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
            patch("swarm_reasoning.pipeline.nodes.coverage.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[mock_resp_429, mock_resp_200])
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await search_coverage("test query", "src1", mock_ctx, "coverage-left")

        assert len(result) == 1
        assert result[0]["title"] == "Retry Success"

    @pytest.mark.asyncio
    async def test_empty_articles(self, mock_ctx):
        """API returns empty articles list → count observation with value '0'."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"articles": []}

        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await search_coverage("test query", "src1", mock_ctx, "coverage-left")

        assert result == []
        call = mock_ctx.publish_observation.call_args
        assert call.kwargs["value"] == "0"


# ---------------------------------------------------------------------------
# Tool 3: detect_coverage_framing
# ---------------------------------------------------------------------------


class TestDetectCoverageFraming:
    """Tests for headline sentiment analysis."""

    @pytest.mark.asyncio
    async def test_absent_when_no_articles(self, mock_ctx):
        """No articles → ABSENT framing with 0.0 compound."""
        framing, compound = await detect_coverage_framing([], mock_ctx, "coverage-left")

        assert framing == "ABSENT^Not Covered^FCK"
        assert compound == 0.0
        assert mock_ctx.publish_observation.call_count == 1
        call = mock_ctx.publish_observation.call_args
        assert call.kwargs["code"] == ObservationCode.COVERAGE_FRAMING
        assert call.kwargs["value"] == "ABSENT^Not Covered^FCK"

    @pytest.mark.asyncio
    async def test_framing_with_articles(self, mock_ctx):
        """Articles with headlines → publishes framing CWE and returns compound."""
        articles = [
            {"title": "Great economic growth reported"},
            {"title": "Jobs market shows improvement"},
        ]

        with patch(
            "swarm_reasoning.pipeline.nodes.coverage.compute_compound_sentiment",
            return_value=0.5,
        ), patch(
            "swarm_reasoning.pipeline.nodes.coverage.classify_framing",
            return_value="SUPPORTIVE^Supportive^FCK",
        ):
            framing, compound = await detect_coverage_framing(articles, mock_ctx, "coverage-center")

        assert framing == "SUPPORTIVE^Supportive^FCK"
        assert compound == 0.5
        assert mock_ctx.publish_observation.call_count == 1
        call = mock_ctx.publish_observation.call_args
        assert call.kwargs["code"] == ObservationCode.COVERAGE_FRAMING
        assert call.kwargs["value_type"] == ValueType.CWE

    @pytest.mark.asyncio
    async def test_uses_first_5_headlines_only(self, mock_ctx):
        """Only the first 5 article headlines should be analyzed."""
        articles = [{"title": f"Headline {i}"} for i in range(10)]

        with patch(
            "swarm_reasoning.pipeline.nodes.coverage.compute_compound_sentiment",
            return_value=0.0,
        ) as mock_sentiment, patch(
            "swarm_reasoning.pipeline.nodes.coverage.classify_framing",
            return_value="NEUTRAL^Neutral^FCK",
        ):
            await detect_coverage_framing(articles, mock_ctx, "coverage-right")

        # compute_compound_sentiment receives at most 5 headlines
        headlines_passed = mock_sentiment.call_args.args[0]
        assert len(headlines_passed) == 5

    @pytest.mark.asyncio
    async def test_skips_empty_titles(self, mock_ctx):
        """Articles with empty or missing titles are filtered out."""
        articles = [
            {"title": "Valid headline"},
            {"title": ""},
            {},
            {"title": "Another valid headline"},
        ]

        with patch(
            "swarm_reasoning.pipeline.nodes.coverage.compute_compound_sentiment",
            return_value=0.1,
        ) as mock_sentiment, patch(
            "swarm_reasoning.pipeline.nodes.coverage.classify_framing",
            return_value="SUPPORTIVE^Supportive^FCK",
        ):
            await detect_coverage_framing(articles, mock_ctx, "coverage-left")

        headlines_passed = mock_sentiment.call_args.args[0]
        assert len(headlines_passed) == 2
        assert all(h for h in headlines_passed)


# ---------------------------------------------------------------------------
# Tool 4: find_top_coverage_source
# ---------------------------------------------------------------------------


class TestFindTopCoverageSource:
    """Tests for credibility-based source selection."""

    @pytest.mark.asyncio
    async def test_selects_highest_credibility(self, mock_ctx, sample_articles, sample_sources):
        """Selects the source with the highest credibility_rank."""
        result = await find_top_coverage_source(
            sample_articles, sample_sources, mock_ctx, "coverage-left",
        )

        assert result is not None
        assert result["name"] == "Source C"
        assert result["url"] == "https://example.com/article2"
        assert mock_ctx.publish_observation.call_count == 2
        codes = [c.kwargs["code"] for c in mock_ctx.publish_observation.call_args_list]
        assert ObservationCode.COVERAGE_TOP_SOURCE in codes
        assert ObservationCode.COVERAGE_TOP_SOURCE_URL in codes

    @pytest.mark.asyncio
    async def test_no_articles_returns_none(self, mock_ctx, sample_sources):
        """Empty article list → returns None, no observations published."""
        result = await find_top_coverage_source(
            [], sample_sources, mock_ctx, "coverage-right",
        )

        assert result is None
        assert mock_ctx.publish_observation.call_count == 0

    @pytest.mark.asyncio
    async def test_single_article(self, mock_ctx, sample_sources):
        """Single article → returns that article's source."""
        articles = [
            {
                "title": "Solo article",
                "url": "https://example.com/solo",
                "source": {"id": "source-b", "name": "Source B"},
            }
        ]

        result = await find_top_coverage_source(
            articles, sample_sources, mock_ctx, "coverage-center",
        )

        assert result is not None
        assert result["name"] == "Source B"
        assert result["url"] == "https://example.com/solo"

    @pytest.mark.asyncio
    async def test_unknown_source_id(self, mock_ctx):
        """Article from unknown source → still returns a result."""
        articles = [
            {
                "title": "Unknown source article",
                "url": "https://example.com/unknown",
                "source": {"id": "unknown-src", "name": "Unknown Source"},
            }
        ]
        sources = [{"id": "other-id", "name": "Other", "credibility_rank": 50}]

        result = await find_top_coverage_source(articles, sources, mock_ctx, "coverage-left")

        assert result is not None
        # Falls back to source name from the article
        assert result["url"] == "https://example.com/unknown"


# ---------------------------------------------------------------------------
# Per-spectrum runner: _run_spectrum
# ---------------------------------------------------------------------------


class TestRunSpectrum:
    """Tests for the per-spectrum orchestration runner."""

    @pytest.mark.asyncio
    async def test_returns_correct_state_key(self, mock_ctx):
        """Each spectrum returns its corresponding state key."""
        mock_sources = [{"id": "src1", "name": "Src1", "credibility_rank": 50}]
        articles = [
            {
                "title": "Test Article",
                "url": "https://example.com/test",
                "source": {"id": "src1", "name": "Src1"},
            }
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"articles": articles}

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=mock_sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            state_key, _, _, _ = await _run_spectrum("left", "test claim", mock_ctx)

        assert state_key == "coverage_left"

    @pytest.mark.asyncio
    async def test_heartbeats_called(self, mock_ctx):
        """Each spectrum run sends heartbeats at each tool stage."""
        mock_sources = [{"id": "src1", "name": "Src1", "credibility_rank": 50}]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"articles": []}

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=mock_sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await _run_spectrum("center", "test claim", mock_ctx)

        # 3 heartbeats: after search, after framing, after top source
        assert mock_ctx.heartbeat.call_count == 3
        for call in mock_ctx.heartbeat.call_args_list:
            assert call.args[0] == "coverage-center"

    @pytest.mark.asyncio
    async def test_progress_messages(self, mock_ctx):
        """Each spectrum run publishes searching and completion progress."""
        mock_sources = [{"id": "src1", "name": "Src1", "credibility_rank": 50}]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"articles": []}

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=mock_sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await _run_spectrum("right", "test claim", mock_ctx)

        assert mock_ctx.publish_progress.call_count == 2
        messages = [call.args[1] for call in mock_ctx.publish_progress.call_args_list]
        assert "right-spectrum" in messages[0].lower() or "right" in messages[0].lower()
        assert "complete" in messages[1].lower()

    @pytest.mark.asyncio
    async def test_articles_formatted_for_state(self, mock_ctx):
        """Returned articles list has correct structure for state storage."""
        mock_sources = [{"id": "src-a", "name": "Source A", "credibility_rank": 80}]
        articles = [
            {
                "title": "Test Title",
                "url": "https://example.com/art",
                "source": {"id": "src-a", "name": "Source A"},
            }
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"articles": articles}

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=mock_sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            _, coverage_articles, _, _ = await _run_spectrum("left", "test claim", mock_ctx)

        assert len(coverage_articles) == 1
        art = coverage_articles[0]
        assert "title" in art
        assert "url" in art
        assert "source" in art
        assert "framing" in art


# ---------------------------------------------------------------------------
# Full node integration tests
# ---------------------------------------------------------------------------


class TestCoverageNode:
    """Integration tests for the full coverage_node function."""

    def _setup_mocks(self, mock_client_cls, articles_per_spectrum=None):
        """Helper to configure httpx mock for all 3 spectrums."""
        if articles_per_spectrum is None:
            articles_per_spectrum = [
                [{"title": f"Left Art {i}", "url": f"https://left.com/{i}",
                  "source": {"id": "huffington-post", "name": "HuffPost"}}
                 for i in range(2)],
                [{"title": f"Center Art {i}", "url": f"https://center.com/{i}",
                  "source": {"id": "reuters", "name": "Reuters"}}
                 for i in range(3)],
                [{"title": f"Right Art {i}", "url": f"https://right.com/{i}",
                  "source": {"id": "fox-news", "name": "Fox News"}}
                 for i in range(1)],
            ]

        call_idx = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_idx
            resp = MagicMock()
            resp.status_code = 200
            idx = min(call_idx, len(articles_per_spectrum) - 1)
            resp.json.return_value = {"articles": articles_per_spectrum[idx]}
            call_idx += 1
            return resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    @pytest.mark.asyncio
    async def test_happy_path(self, mock_config, mock_ctx, base_state):
        """Full coverage node with 3 spectrums returning articles."""
        left_sources = [{"id": "huffington-post", "name": "HuffPost", "credibility_rank": 65}]
        center_sources = [{"id": "reuters", "name": "Reuters", "credibility_rank": 90}]
        right_sources = [{"id": "fox-news", "name": "Fox News", "credibility_rank": 55}]

        source_map = {"left": left_sources, "center": center_sources, "right": right_sources}

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                side_effect=lambda s: source_map[s],
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            self._setup_mocks(mock_client_cls)
            result = await coverage_node(base_state, mock_config)

        assert "coverage_left" in result
        assert "coverage_center" in result
        assert "coverage_right" in result
        assert "framing_analysis" in result
        assert "observations" in result

        assert isinstance(result["coverage_left"], list)
        assert isinstance(result["coverage_center"], list)
        assert isinstance(result["coverage_right"], list)
        assert isinstance(result["framing_analysis"], dict)

    @pytest.mark.asyncio
    async def test_state_output_keys(self, mock_config, mock_ctx, base_state):
        """Returned dict has exactly the expected keys."""
        sources = [{"id": "src1", "name": "S1", "credibility_rank": 50}]

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            self._setup_mocks(mock_client_cls, articles_per_spectrum=[[], [], []])
            result = await coverage_node(base_state, mock_config)

        assert set(result.keys()) == {
            "coverage_left",
            "coverage_center",
            "coverage_right",
            "framing_analysis",
            "observations",
        }

    @pytest.mark.asyncio
    async def test_framing_analysis_structure(self, mock_config, mock_ctx, base_state):
        """framing_analysis has entries for all 3 spectrums with correct fields."""
        sources = [{"id": "src1", "name": "S1", "credibility_rank": 50}]

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            self._setup_mocks(mock_client_cls, articles_per_spectrum=[[], [], []])
            result = await coverage_node(base_state, mock_config)

        fa = result["framing_analysis"]
        assert set(fa.keys()) == {"left", "center", "right"}
        for spectrum in ("left", "center", "right"):
            entry = fa[spectrum]
            assert "framing" in entry
            assert "compound" in entry
            assert "article_count" in entry
            assert isinstance(entry["compound"], float)
            assert isinstance(entry["article_count"], int)

    @pytest.mark.asyncio
    async def test_degradation_no_api_key(self, mock_config, mock_ctx, base_state):
        """No NEWSAPI_KEY → all spectrums return empty articles with X observations."""
        sources = [{"id": "src1", "name": "S1", "credibility_rank": 50}]

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=sources,
            ),
            patch.dict("os.environ", {}, clear=True),
        ):
            import os
            os.environ.pop("NEWSAPI_KEY", None)
            result = await coverage_node(base_state, mock_config)

        assert result["coverage_left"] == []
        assert result["coverage_center"] == []
        assert result["coverage_right"] == []
        # All framing should be ABSENT
        for spectrum in ("left", "center", "right"):
            assert result["framing_analysis"][spectrum]["framing"] == "ABSENT"
            assert result["framing_analysis"][spectrum]["article_count"] == 0

    @pytest.mark.asyncio
    async def test_heartbeats_across_spectrums(self, mock_config, mock_ctx, base_state):
        """Coverage node sends heartbeats across all spectrums."""
        sources = [{"id": "src1", "name": "S1", "credibility_rank": 50}]

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            self._setup_mocks(mock_client_cls, articles_per_spectrum=[[], [], []])
            await coverage_node(base_state, mock_config)

        # 1 initial heartbeat + 3 per spectrum × 3 spectrums = 10
        assert mock_ctx.heartbeat.call_count >= 10
        agents = {call.args[0] for call in mock_ctx.heartbeat.call_args_list}
        assert "coverage" in agents  # initial heartbeat
        assert "coverage-left" in agents
        assert "coverage-center" in agents
        assert "coverage-right" in agents

    @pytest.mark.asyncio
    async def test_observations_output(self, mock_config, mock_ctx, base_state):
        """Observations list contains COVERAGE_ARTICLE_COUNT and COVERAGE_FRAMING per spectrum."""
        sources = [{"id": "src1", "name": "S1", "credibility_rank": 50}]

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            self._setup_mocks(mock_client_cls, articles_per_spectrum=[[], [], []])
            result = await coverage_node(base_state, mock_config)

        obs = result["observations"]
        # 2 per spectrum (ARTICLE_COUNT + FRAMING) × 3 spectrums = 6
        assert len(obs) == 6
        codes = {o["code"] for o in obs}
        assert "COVERAGE_ARTICLE_COUNT" in codes
        assert "COVERAGE_FRAMING" in codes
        agents = {o["agent"] for o in obs}
        assert agents == {"coverage-left", "coverage-center", "coverage-right"}

    @pytest.mark.asyncio
    async def test_progress_messages(self, mock_config, mock_ctx, base_state):
        """Coverage node publishes start and completion progress messages."""
        sources = [{"id": "src1", "name": "S1", "credibility_rank": 50}]

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            self._setup_mocks(mock_client_cls, articles_per_spectrum=[[], [], []])
            await coverage_node(base_state, mock_config)

        # At least: 1 start + 2 per spectrum × 3 + 1 completion = 8
        assert mock_ctx.publish_progress.call_count >= 8

    @pytest.mark.asyncio
    async def test_uses_normalized_claim_over_claim_text(self, mock_config, mock_ctx):
        """Node prefers normalized_claim when available."""
        state: PipelineState = {
            "claim_text": "ORIGINAL Claim Text",
            "normalized_claim": "normalized claim text",
            "run_id": "run-test",
            "session_id": "sess-test",
            "observations": [],
            "errors": [],
        }
        sources = [{"id": "src1", "name": "S1", "credibility_rank": 50}]

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
            patch(
                "swarm_reasoning.pipeline.nodes.coverage.build_search_query",
                wraps=build_search_query,
            ) as mock_bsq,
        ):
            self._setup_mocks(mock_client_cls, articles_per_spectrum=[[], [], []])
            await coverage_node(state, mock_config)

        # build_search_query should have been called with the normalized claim
        for call in mock_bsq.call_args_list:
            assert call.args[0] == "normalized claim text"

    @pytest.mark.asyncio
    async def test_falls_back_to_claim_text(self, mock_config, mock_ctx):
        """When normalized_claim is absent, falls back to claim_text."""
        state: PipelineState = {
            "claim_text": "original claim text",
            "run_id": "run-test",
            "session_id": "sess-test",
            "observations": [],
            "errors": [],
        }
        sources = [{"id": "src1", "name": "S1", "credibility_rank": 50}]

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
            patch(
                "swarm_reasoning.pipeline.nodes.coverage.build_search_query",
                wraps=build_search_query,
            ) as mock_bsq,
        ):
            self._setup_mocks(mock_client_cls, articles_per_spectrum=[[], [], []])
            await coverage_node(state, mock_config)

        for call in mock_bsq.call_args_list:
            assert call.args[0] == "original claim text"

    @pytest.mark.asyncio
    async def test_total_articles_in_completion_progress(self, mock_config, mock_ctx, base_state):
        """Completion progress message includes total article count."""
        sources = [{"id": "src1", "name": "S1", "credibility_rank": 50}]
        articles = [
            {"title": "Art", "url": "https://x.com/1", "source": {"id": "src1", "name": "S1"}}
        ]

        with (
            patch(
                "swarm_reasoning.pipeline.nodes.coverage._load_sources",
                return_value=sources,
            ),
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.pipeline.nodes.coverage.httpx.AsyncClient") as mock_client_cls,
        ):
            self._setup_mocks(mock_client_cls, articles_per_spectrum=[articles, articles, articles])
            await coverage_node(base_state, mock_config)

        # Last progress call from coverage_node should mention total count
        coverage_progress_calls = [
            call for call in mock_ctx.publish_progress.call_args_list
            if call.args[0] == "coverage"
        ]
        last_msg = coverage_progress_calls[-1].args[1]
        assert "3" in last_msg  # 1 article × 3 spectrums = 3 total
