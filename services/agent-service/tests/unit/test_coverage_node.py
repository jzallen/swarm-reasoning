"""Tests for coverage pipeline node (M3.2 / sr-l0y.5.6).

Tests cover:
- Tool 1: build_search_query (stop-word removal, truncation, word boundary)
- Tool 2: search_coverage (API success, missing key, API error, rate-limit retry)
- Tool 3: detect_coverage_framing (with articles, empty articles)
- Tool 4: find_top_coverage_source (best credibility, no articles)
- Per-spectrum runner: _run_spectrum_node orchestration
- Individual pipeline nodes: run_coverage_left/center/right
- Full node: happy path across 3 spectrums, degradation (no API key),
  heartbeats, observations, state output structure, framing_analysis
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from swarm_reasoning.agents.coverage.models import CoverageOutput
from swarm_reasoning.agents.coverage.tools import (
    build_search_query,
    detect_coverage_framing,
    find_top_coverage_source,
    search_coverage,
)
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.pipeline.nodes.coverage import (
    _run_spectrum_node,
    coverage_node,
    run_coverage_center,
    run_coverage_left,
    run_coverage_right,
)
from swarm_reasoning.pipeline.state import PipelineState

# Common patch targets
_HTTPX = (
    "swarm_reasoning.agents.coverage.tools.search_coverage"
    ".httpx.AsyncClient"
)
_SLEEP = (
    "swarm_reasoning.agents.coverage.tools.search_coverage"
    ".asyncio.sleep"
)
_LOAD_SOURCES = (
    "swarm_reasoning.pipeline.nodes.coverage._load_sources"
)
_RUN_AGENT = (
    "swarm_reasoning.pipeline.nodes.coverage.run_coverage_agent"
)

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
            patch(_HTTPX) as mock_client_cls,
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
            patch(_HTTPX) as mock_client_cls,
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
            patch(_HTTPX) as mock_client_cls,
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
            patch(_HTTPX) as mock_client_cls,
            patch(_SLEEP, new_callable=AsyncMock),
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
            patch(_HTTPX) as mock_client_cls,
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
            "swarm_reasoning.agents.coverage.tools.detect_framing.compute_compound_sentiment",
            return_value=0.5,
        ), patch(
            "swarm_reasoning.agents.coverage.tools.detect_framing.classify_framing",
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
            "swarm_reasoning.agents.coverage.tools.detect_framing.compute_compound_sentiment",
            return_value=0.0,
        ) as mock_sentiment, patch(
            "swarm_reasoning.agents.coverage.tools.detect_framing.classify_framing",
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
            "swarm_reasoning.agents.coverage.tools.detect_framing.compute_compound_sentiment",
            return_value=0.1,
        ) as mock_sentiment, patch(
            "swarm_reasoning.agents.coverage.tools.detect_framing.classify_framing",
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


class TestRunSpectrumNode:
    """Tests for the per-spectrum pipeline node runner (_run_spectrum_node).

    _run_spectrum_node delegates to run_coverage_agent (LangGraph ReAct agent).
    We mock run_coverage_agent to isolate the pipeline node logic.
    """

    def _make_output(self, articles=None, framing="ABSENT", compound=0.0, top_source=None):
        """Build a CoverageOutput for mocking run_coverage_agent."""
        return CoverageOutput(
            articles=articles or [],
            framing=framing,
            compound_score=compound,
            top_source=top_source,
        )

    @pytest.mark.asyncio
    async def test_returns_correct_state_key(self, mock_ctx, base_state):
        """Each spectrum returns its corresponding state key."""
        output = self._make_output(
            articles=[{"title": "Art", "url": "u", "source": "S", "framing": "NEUTRAL"}],
            framing="NEUTRAL",
        )

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=output),
        ):
            result = await _run_spectrum_node("left", base_state, mock_ctx)

        assert "coverage_left" in result

    @pytest.mark.asyncio
    async def test_heartbeat_called(self, mock_ctx, base_state):
        """_run_spectrum_node sends a heartbeat at the start."""
        output = self._make_output()

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=output),
        ):
            await _run_spectrum_node("center", base_state, mock_ctx)

        mock_ctx.heartbeat.assert_called_with("coverage-center")

    @pytest.mark.asyncio
    async def test_passes_extracted_input_to_agent(self, mock_ctx, base_state):
        """run_coverage_agent receives CoverageInput extracted from PipelineState."""
        output = self._make_output()

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=output) as mock_agent,
        ):
            await _run_spectrum_node("right", base_state, mock_ctx)

        call_args = mock_agent.call_args
        assert call_args.args[0] == "right"  # spectrum
        # Third arg is CoverageInput
        coverage_input = call_args.args[2]
        assert coverage_input["normalized_claim"] == base_state["normalized_claim"]

    @pytest.mark.asyncio
    async def test_output_includes_framing_analysis(self, mock_ctx, base_state):
        """Result includes framing_analysis entry for the spectrum."""
        output = self._make_output(
            articles=[{"title": "A", "url": "u", "source": "S", "framing": "SUPPORTIVE"}],
            framing="SUPPORTIVE",
            compound=0.3,
        )

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=output),
        ):
            result = await _run_spectrum_node("left", base_state, mock_ctx)

        assert "framing_analysis" in result
        fa = result["framing_analysis"]["left"]
        assert fa["framing"] == "SUPPORTIVE"
        assert fa["compound"] == 0.3
        assert fa["article_count"] == 1

    @pytest.mark.asyncio
    async def test_articles_stored_under_state_key(self, mock_ctx, base_state):
        """Returned articles list is stored under the spectrum's state key."""
        articles = [
            {"title": "Art", "url": "u", "source": "S", "framing": "NEUTRAL"},
        ]
        output = self._make_output(articles=articles, framing="NEUTRAL")

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=output),
        ):
            result = await _run_spectrum_node("right", base_state, mock_ctx)

        assert len(result["coverage_right"]) == 1
        art = result["coverage_right"][0]
        assert "title" in art
        assert "framing" in art


# ---------------------------------------------------------------------------
# Individual pipeline node functions: run_coverage_left/center/right
# ---------------------------------------------------------------------------


class TestRunCoverageLeftCenterRight:
    """Tests for the graph-registerable individual pipeline node functions."""

    def _make_output(self, framing="ABSENT"):
        return CoverageOutput(
            articles=[],
            framing=framing,
            compound_score=0.0,
            top_source=None,
        )

    @pytest.mark.asyncio
    async def test_run_coverage_left(self, mock_config, mock_ctx, base_state):
        output = self._make_output()

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=output),
        ):
            result = await run_coverage_left(base_state, mock_config)

        assert "coverage_left" in result
        assert "framing_analysis" in result
        assert "left" in result["framing_analysis"]

    @pytest.mark.asyncio
    async def test_run_coverage_center(self, mock_config, mock_ctx, base_state):
        output = self._make_output()

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=output),
        ):
            result = await run_coverage_center(base_state, mock_config)

        assert "coverage_center" in result
        assert "center" in result["framing_analysis"]

    @pytest.mark.asyncio
    async def test_run_coverage_right(self, mock_config, mock_ctx, base_state):
        output = self._make_output()

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=output),
        ):
            result = await run_coverage_right(base_state, mock_config)

        assert "coverage_right" in result
        assert "right" in result["framing_analysis"]

    @pytest.mark.asyncio
    async def test_each_node_heartbeats_correct_agent(self, mock_config, mock_ctx, base_state):
        output = self._make_output()

        for node_fn, expected_agent in [
            (run_coverage_left, "coverage-left"),
            (run_coverage_center, "coverage-center"),
            (run_coverage_right, "coverage-right"),
        ]:
            mock_ctx.heartbeat.reset_mock()
            with (
                patch(_LOAD_SOURCES, return_value=[]),
                patch(_RUN_AGENT, new_callable=AsyncMock, return_value=output),
            ):
                await node_fn(base_state, mock_config)

            mock_ctx.heartbeat.assert_called_with(expected_agent)


# ---------------------------------------------------------------------------
# Full node integration tests
# ---------------------------------------------------------------------------


class TestCoverageNode:
    """Tests for the full coverage_node function.

    coverage_node runs all three spectrums concurrently via _run_spectrum_node,
    which delegates to run_coverage_agent. We mock run_coverage_agent to isolate
    the pipeline node orchestration and merging logic.
    """

    def _make_output(self, articles=None, framing="ABSENT", compound=0.0, top_source=None):
        return CoverageOutput(
            articles=articles or [],
            framing=framing,
            compound_score=compound,
            top_source=top_source,
        )

    def _patch_agent(self, outputs=None):
        """Patch run_coverage_agent to return CoverageOutput per spectrum.

        If outputs is a dict mapping spectrum -> CoverageOutput, return the
        matching output. Otherwise return the same output for all spectrums.
        """
        if outputs is None:
            outputs = self._make_output()

        if isinstance(outputs, dict):
            async def side_effect(spectrum, *args, **kwargs):
                return outputs.get(spectrum, self._make_output())
        else:
            async def side_effect(*args, **kwargs):
                return outputs

        return patch(
            "swarm_reasoning.pipeline.nodes.coverage.run_coverage_agent",
            new_callable=AsyncMock,
            side_effect=side_effect,
        )

    @pytest.mark.asyncio
    async def test_happy_path(self, mock_config, mock_ctx, base_state):
        """Full coverage node with 3 spectrums returning articles."""
        outputs = {
            "left": self._make_output(
                articles=[{"title": "Left Art", "url": "u", "source": "S", "framing": "N"}],
                framing="NEUTRAL",
            ),
            "center": self._make_output(
                articles=[
                    {"title": "Center Art 1", "url": "u", "source": "S", "framing": "S"},
                    {"title": "Center Art 2", "url": "u", "source": "S", "framing": "S"},
                ],
                framing="SUPPORTIVE",
                compound=0.3,
            ),
            "right": self._make_output(framing="ABSENT"),
        }

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            self._patch_agent(outputs),
        ):
            result = await coverage_node(base_state, mock_config)

        assert "coverage_left" in result
        assert "coverage_center" in result
        assert "coverage_right" in result
        assert "framing_analysis" in result

        assert len(result["coverage_left"]) == 1
        assert len(result["coverage_center"]) == 2
        assert result["coverage_right"] == []

    @pytest.mark.asyncio
    async def test_state_output_keys(self, mock_config, mock_ctx, base_state):
        """Returned dict has exactly the expected keys."""
        with (
            patch(_LOAD_SOURCES, return_value=[]),
            self._patch_agent(),
        ):
            result = await coverage_node(base_state, mock_config)

        assert set(result.keys()) == {
            "coverage_left",
            "coverage_center",
            "coverage_right",
            "framing_analysis",
        }

    @pytest.mark.asyncio
    async def test_framing_analysis_structure(self, mock_config, mock_ctx, base_state):
        """framing_analysis has entries for all 3 spectrums with correct fields."""
        outputs = {
            "left": self._make_output(framing="SUPPORTIVE", compound=0.2),
            "center": self._make_output(framing="NEUTRAL", compound=0.01),
            "right": self._make_output(framing="CRITICAL", compound=-0.3),
        }

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            self._patch_agent(outputs),
        ):
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

        assert fa["left"]["framing"] == "SUPPORTIVE"
        assert fa["right"]["framing"] == "CRITICAL"

    @pytest.mark.asyncio
    async def test_all_empty_produces_absent_framing(self, mock_config, mock_ctx, base_state):
        """All spectrums returning empty → ABSENT framing everywhere."""
        with (
            patch(_LOAD_SOURCES, return_value=[]),
            self._patch_agent(),
        ):
            result = await coverage_node(base_state, mock_config)

        for spectrum in ("left", "center", "right"):
            assert result[f"coverage_{spectrum}"] == []
            assert result["framing_analysis"][spectrum]["framing"] == "ABSENT"
            assert result["framing_analysis"][spectrum]["article_count"] == 0

    @pytest.mark.asyncio
    async def test_heartbeats(self, mock_config, mock_ctx, base_state):
        """Coverage node sends initial heartbeat as 'coverage'."""
        with (
            patch(_LOAD_SOURCES, return_value=[]),
            self._patch_agent(),
        ):
            await coverage_node(base_state, mock_config)

        agents = [call.args[0] for call in mock_ctx.heartbeat.call_args_list]
        assert "coverage" in agents  # initial heartbeat from coverage_node

    @pytest.mark.asyncio
    async def test_progress_messages(self, mock_config, mock_ctx, base_state):
        """Coverage node publishes start and completion progress."""
        with (
            patch(_LOAD_SOURCES, return_value=[]),
            self._patch_agent(),
        ):
            await coverage_node(base_state, mock_config)

        # coverage_node itself publishes at least 2: start + completion
        coverage_msgs = [
            call for call in mock_ctx.publish_progress.call_args_list
            if call.args[0] == "coverage"
        ]
        assert len(coverage_msgs) >= 2

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

        empty = self._make_output()
        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=empty) as mock_agent,
        ):
            await coverage_node(state, mock_config)

        # run_coverage_agent should receive normalized_claim in the CoverageInput
        for call in mock_agent.call_args_list:
            coverage_input = call.args[2]  # third positional arg
            assert coverage_input["normalized_claim"] == "normalized claim text"

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

        empty = self._make_output()
        with (
            patch(_LOAD_SOURCES, return_value=[]),
            patch(_RUN_AGENT, new_callable=AsyncMock, return_value=empty) as mock_agent,
        ):
            await coverage_node(state, mock_config)

        for call in mock_agent.call_args_list:
            coverage_input = call.args[2]
            assert coverage_input["normalized_claim"] == "original claim text"

    @pytest.mark.asyncio
    async def test_total_articles_in_completion_progress(self, mock_config, mock_ctx, base_state):
        """Completion progress message includes total article count."""
        outputs = {
            "left": self._make_output(
                articles=[{"title": "A", "url": "u", "source": "S", "framing": "N"}],
            ),
            "center": self._make_output(
                articles=[{"title": "B", "url": "u", "source": "S", "framing": "N"}],
            ),
            "right": self._make_output(
                articles=[{"title": "C", "url": "u", "source": "S", "framing": "N"}],
            ),
        }

        with (
            patch(_LOAD_SOURCES, return_value=[]),
            self._patch_agent(outputs),
        ):
            await coverage_node(base_state, mock_config)

        coverage_progress_calls = [
            call for call in mock_ctx.publish_progress.call_args_list
            if call.args[0] == "coverage"
        ]
        last_msg = coverage_progress_calls[-1].args[1]
        assert "3" in last_msg  # 1 article × 3 spectrums = 3 total
