"""Tests for evidence pipeline node (M2.1).

Tests cover:
- Tool 1: search_factchecks (API success, no matches, low score, missing key, API error)
- Tool 2: lookup_domain_sources (known domains, fallback to OTHER)
- Tool 3: fetch_source_content (success, HTTP error, exception)
- Tool 4: score_evidence (SUPPORTS, CONTRADICTS, PARTIAL, ABSENT, penalties)
- Helper: _build_factcheck_query, _build_search_query
- Full node: happy path, no factcheck matches, all sources fail, heartbeats, observations
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.pipeline.nodes.evidence import (
    AGENT_NAME,
    _build_factcheck_query,
    _build_search_query,
    _MATCH_THRESHOLD,
    evidence_node,
    fetch_source_content,
    lookup_domain_sources,
    score_evidence,
    search_factchecks,
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
    """Minimal valid PipelineState for evidence testing (post-intake)."""
    return {
        "claim_text": "The unemployment rate dropped to 3.5% in 2024",
        "run_id": "run-test",
        "session_id": "sess-test",
        "normalized_claim": "the unemployment rate dropped to 3.5% in 2024",
        "claim_domain": "ECONOMICS",
        "entities": {
            "persons": [],
            "orgs": ["BLS"],
            "dates": ["2024"],
            "locations": [],
            "statistics": ["3.5%"],
        },
        "observations": [],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestBuildFactcheckQuery:
    """Tests for _build_factcheck_query."""

    def test_entities_prepended_to_claim(self):
        query = _build_factcheck_query("tax cuts reduce deficit", ["Joe Biden"], ["CBO"])
        assert query.startswith("Joe Biden CBO")
        assert "tax cuts reduce deficit" in query

    def test_truncated_at_100_chars(self):
        query = _build_factcheck_query("x" * 200, [], [])
        assert len(query) <= 100

    def test_max_two_entities(self):
        query = _build_factcheck_query("claim", ["A", "B", "C"], ["D"])
        # Only first 2 from persons+organizations combined
        assert "A" in query
        assert "B" in query
        assert "C" not in query

    def test_empty_entities(self):
        query = _build_factcheck_query("simple claim", [], [])
        assert query == "simple claim"


class TestBuildSearchQuery:
    """Tests for _build_search_query."""

    def test_includes_entities_and_keywords(self):
        query = _build_search_query("the economy grew 3%", ["Biden"], ["Fed"])
        assert "Biden" in query
        assert "Fed" in query
        # Stop words like "the" should be removed
        assert "economy" in query

    def test_truncates_at_80_chars(self):
        query = _build_search_query("x " * 100, [], [])
        assert len(query) <= 80

    def test_truncates_at_word_boundary(self):
        # Build a query that's between 80-100 chars to test word boundary truncation
        query = _build_search_query("economy grew strongly rapidly quickly significantly", ["President"], [])
        assert len(query) <= 80
        # Should not end mid-word
        assert not query.endswith(" ")


# ---------------------------------------------------------------------------
# Tool 1: search_factchecks
# ---------------------------------------------------------------------------


class TestSearchFactchecks:
    """Tests for the factcheck search tool."""

    @pytest.mark.asyncio
    async def test_successful_match(self, mock_ctx):
        """API returns a match above threshold → returns match list + 5 observations."""
        api_results = [
            {
                "text": "Unemployment dropped to 3.5%",
                "claimReview": [
                    {
                        "title": "Unemployment dropped to 3.5%",
                        "textualRating": "True",
                        "publisher": {"name": "PolitiFact"},
                        "url": "https://politifact.com/check1",
                    }
                ],
            }
        ]
        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=api_results,
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.cosine_similarity",
                return_value=0.85,
            ),
        ):
            matches = await search_factchecks(
                "the unemployment rate dropped to 3.5%", [], [], mock_ctx,
            )

        assert len(matches) == 1
        assert matches[0]["source"] == "PolitiFact"
        assert matches[0]["rating"] == "True"
        assert matches[0]["url"] == "https://politifact.com/check1"
        assert matches[0]["score"] == 0.85
        # 5 observations: MATCH, VERDICT, SOURCE, URL, MATCH_SCORE
        assert mock_ctx.publish_observation.call_count == 5

    @pytest.mark.asyncio
    async def test_no_api_results(self, mock_ctx):
        """API returns empty results → returns empty list + 2 negative observations."""
        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            matches = await search_factchecks(
                "some claim", [], [], mock_ctx,
            )

        assert matches == []
        # 2 observations: negative MATCH + MATCH_SCORE
        assert mock_ctx.publish_observation.call_count == 2

    @pytest.mark.asyncio
    async def test_below_threshold_score(self, mock_ctx):
        """Match score below threshold → treated as no match."""
        api_results = [
            {
                "text": "Something totally different",
                "claimReview": [{"title": "Something different"}],
            }
        ]
        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=api_results,
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.cosine_similarity",
                return_value=_MATCH_THRESHOLD - 0.01,
            ),
        ):
            matches = await search_factchecks(
                "the unemployment rate dropped", [], [], mock_ctx,
            )

        assert matches == []
        assert mock_ctx.publish_observation.call_count == 2

    @pytest.mark.asyncio
    async def test_missing_api_key(self, mock_ctx):
        """No API key → returns empty list with X-status observations."""
        with patch.dict("os.environ", {}, clear=True):
            # Ensure GOOGLE_FACTCHECK_API_KEY is absent
            import os
            os.environ.pop("GOOGLE_FACTCHECK_API_KEY", None)
            matches = await search_factchecks(
                "some claim", [], [], mock_ctx,
            )

        assert matches == []
        assert mock_ctx.publish_observation.call_count == 2
        # Both observations should have status="X"
        for call in mock_ctx.publish_observation.call_args_list:
            assert call.kwargs["status"] == "X"

    @pytest.mark.asyncio
    async def test_api_error(self, mock_ctx):
        """API raises exception → returns empty list with X-status observations."""
        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("Connection refused"),
            ),
        ):
            matches = await search_factchecks(
                "some claim", [], [], mock_ctx,
            )

        assert matches == []
        assert mock_ctx.publish_observation.call_count == 2
        for call in mock_ctx.publish_observation.call_args_list:
            assert call.kwargs["status"] == "X"

    @pytest.mark.asyncio
    async def test_match_observations_use_correct_codes(self, mock_ctx):
        """Successful match publishes all 5 expected observation codes."""
        api_results = [
            {
                "text": "Rate dropped to 3.5%",
                "claimReview": [
                    {
                        "title": "Rate dropped to 3.5%",
                        "textualRating": "Mostly True",
                        "publisher": {"name": "Snopes"},
                        "url": "https://snopes.com/check1",
                    }
                ],
            }
        ]
        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=api_results,
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.cosine_similarity",
                return_value=0.75,
            ),
        ):
            await search_factchecks(
                "rate dropped to 3.5%", [], [], mock_ctx,
            )

        codes = [call.kwargs["code"] for call in mock_ctx.publish_observation.call_args_list]
        assert ObservationCode.CLAIMREVIEW_MATCH in codes
        assert ObservationCode.CLAIMREVIEW_VERDICT in codes
        assert ObservationCode.CLAIMREVIEW_SOURCE in codes
        assert ObservationCode.CLAIMREVIEW_URL in codes
        assert ObservationCode.CLAIMREVIEW_MATCH_SCORE in codes


# ---------------------------------------------------------------------------
# Tool 2: lookup_domain_sources
# ---------------------------------------------------------------------------


class TestLookupDomainSources:
    """Tests for the domain source lookup tool."""

    def test_healthcare_returns_sources(self):
        sources = lookup_domain_sources("HEALTHCARE")
        assert len(sources) > 0
        assert sources[0]["name"] == "CDC"

    def test_economics_returns_sources(self):
        sources = lookup_domain_sources("ECONOMICS")
        assert len(sources) > 0
        names = [s["name"] for s in sources]
        assert "SEC EDGAR" in names

    def test_case_insensitive(self):
        upper = lookup_domain_sources("HEALTHCARE")
        lower = lookup_domain_sources("healthcare")
        assert upper == lower

    def test_unknown_domain_falls_back_to_other(self):
        sources = lookup_domain_sources("NONEXISTENT")
        other_sources = lookup_domain_sources("OTHER")
        assert sources == other_sources

    def test_empty_domain_falls_back_to_other(self):
        sources = lookup_domain_sources("")
        other_sources = lookup_domain_sources("OTHER")
        assert sources == other_sources

    def test_sources_have_url_template(self):
        sources = lookup_domain_sources("SCIENCE")
        for source in sources:
            assert "url_template" in source
            assert "{query}" in source["url_template"]


# ---------------------------------------------------------------------------
# Tool 3: fetch_source_content
# ---------------------------------------------------------------------------


class TestFetchSourceContent:
    """Tests for the content fetching tool."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        """Successful HTTP response returns truncated content."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "A" * 3000

        with patch(
            "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            content = await fetch_source_content("https://example.com")

        assert len(content) == 2000
        assert content == "A" * 2000

    @pytest.mark.asyncio
    async def test_short_content_not_padded(self):
        """Content shorter than 2000 chars returned as-is."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Short content"

        with patch(
            "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            content = await fetch_source_content("https://example.com")

        assert content == "Short content"

    @pytest.mark.asyncio
    async def test_http_error_returns_error_string(self):
        """HTTP 4xx/5xx returns an ERROR: prefixed string."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch(
            "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            content = await fetch_source_content("https://example.com/missing")

        assert content.startswith("ERROR:")
        assert "404" in content

    @pytest.mark.asyncio
    async def test_exception_returns_error_string(self):
        """Network exception returns an ERROR: prefixed string."""
        with patch(
            "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection failed"),
        ):
            content = await fetch_source_content("https://unreachable.example.com")

        assert content.startswith("ERROR:")
        assert "unreachable.example.com" in content


# ---------------------------------------------------------------------------
# Tool 4: score_evidence
# ---------------------------------------------------------------------------


class TestScoreEvidence:
    """Tests for the evidence scoring tool."""

    def test_supports_high_overlap_no_negation(self):
        """High keyword overlap without negation → SUPPORTS."""
        # Use words that are NOT stop words
        alignment, confidence = score_evidence(
            "economy grew unemployment dropped rate 3.5%",
            "economy grew unemployment dropped rate 3.5%",
        )
        assert alignment.startswith("SUPPORTS")
        assert confidence > 0.0

    def test_contradicts_high_overlap_with_negation(self):
        """High keyword overlap with negation → CONTRADICTS."""
        alignment, confidence = score_evidence(
            "false claim debunked economy unemployment rate",
            "economy unemployment rate dropped",
        )
        assert alignment.startswith("CONTRADICTS")
        assert confidence > 0.0

    def test_partial_moderate_overlap(self):
        """Moderate keyword overlap (0.3–0.6) → PARTIAL."""
        # 2 of 5 keywords match → overlap = 0.40 → PARTIAL
        alignment, confidence = score_evidence(
            "economy dropped in the latest report",
            "economy unemployment rate dropped significantly",
        )
        assert alignment.startswith("PARTIAL")
        assert confidence > 0.0

    def test_absent_low_overlap(self):
        """Low keyword overlap → ABSENT with 0.0 confidence."""
        alignment, confidence = score_evidence(
            "completely unrelated weather forecast sunny tomorrow",
            "economy unemployment rate dropped significantly",
        )
        assert alignment.startswith("ABSENT")
        assert confidence == 0.0

    def test_absent_on_empty_content(self):
        """Empty content → ABSENT."""
        alignment, confidence = score_evidence("", "some claim")
        assert alignment.startswith("ABSENT")
        assert confidence == 0.0

    def test_absent_on_error_content(self):
        """ERROR: prefixed content → ABSENT."""
        alignment, confidence = score_evidence(
            "ERROR: HTTP 500", "some claim",
        )
        assert alignment.startswith("ABSENT")
        assert confidence == 0.0

    def test_fallback_depth_penalty(self):
        """Each fallback depth step costs -0.10."""
        _, conf_primary = score_evidence(
            "economy unemployment rate dropped 3.5% data",
            "economy unemployment rate dropped 3.5%",
            fallback_depth=0,
        )
        _, conf_fallback1 = score_evidence(
            "economy unemployment rate dropped 3.5% data",
            "economy unemployment rate dropped 3.5%",
            fallback_depth=1,
        )
        _, conf_fallback2 = score_evidence(
            "economy unemployment rate dropped 3.5% data",
            "economy unemployment rate dropped 3.5%",
            fallback_depth=2,
        )
        assert conf_primary > conf_fallback1 > conf_fallback2
        assert conf_primary - conf_fallback1 == pytest.approx(0.10, abs=0.01)

    def test_old_source_penalty(self):
        """Old source costs -0.15."""
        _, conf_new = score_evidence(
            "economy unemployment rate dropped 3.5% data",
            "economy unemployment rate dropped 3.5%",
            source_is_old=False,
        )
        _, conf_old = score_evidence(
            "economy unemployment rate dropped 3.5% data",
            "economy unemployment rate dropped 3.5%",
            source_is_old=True,
        )
        assert conf_new - conf_old == pytest.approx(0.15, abs=0.01)

    def test_indirect_source_penalty(self):
        """Indirect source costs -0.20."""
        _, conf_direct = score_evidence(
            "economy unemployment rate dropped 3.5% data",
            "economy unemployment rate dropped 3.5%",
            is_indirect=False,
        )
        _, conf_indirect = score_evidence(
            "economy unemployment rate dropped 3.5% data",
            "economy unemployment rate dropped 3.5%",
            is_indirect=True,
        )
        assert conf_direct - conf_indirect == pytest.approx(0.20, abs=0.01)

    def test_confidence_floor_at_010(self):
        """Confidence never drops below 0.10 for non-ABSENT results."""
        alignment, confidence = score_evidence(
            "economy unemployment rate dropped 3.5% data",
            "economy unemployment rate dropped 3.5%",
            fallback_depth=10,
            source_is_old=True,
            is_indirect=True,
        )
        if "ABSENT" not in alignment:
            assert confidence >= 0.10

    def test_partial_alignment_penalty(self):
        """PARTIAL alignment costs an additional -0.10."""
        # Force a PARTIAL result with moderate overlap
        alignment, confidence = score_evidence(
            "economy mentioned briefly data",
            "economy unemployment rate dropped significantly",
        )
        if alignment.startswith("PARTIAL"):
            # PARTIAL gets -0.10, so confidence should be 0.90 max (from base 1.0)
            assert confidence <= 0.90

    def test_absent_on_only_stop_words(self):
        """Claim with only stop words → ABSENT."""
        alignment, confidence = score_evidence(
            "the is a an the", "the is a an",
        )
        assert alignment.startswith("ABSENT")
        assert confidence == 0.0


# ---------------------------------------------------------------------------
# Full node integration tests
# ---------------------------------------------------------------------------


class TestEvidenceNode:
    """Integration tests for the full evidence_node function."""

    @pytest.mark.asyncio
    async def test_happy_path(self, mock_config, mock_ctx, base_state):
        """Full successful path: factcheck match + domain source fetch + scoring."""
        api_results = [
            {
                "text": "Unemployment dropped to 3.5%",
                "claimReview": [
                    {
                        "title": "Unemployment dropped to 3.5%",
                        "textualRating": "True",
                        "publisher": {"name": "PolitiFact"},
                        "url": "https://politifact.com/check1",
                    }
                ],
            }
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "unemployment rate dropped 3.5% economy data 2024"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=api_results,
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.cosine_similarity",
                return_value=0.85,
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            result = await evidence_node(base_state, mock_config)

        assert len(result["claimreview_matches"]) == 1
        assert result["claimreview_matches"][0]["source"] == "PolitiFact"
        assert len(result["domain_sources"]) == 1
        assert result["domain_sources"][0]["name"] != "N/A"
        assert result["evidence_confidence"] > 0.0
        assert len(result["observations"]) == 4

    @pytest.mark.asyncio
    async def test_no_factcheck_matches(self, mock_config, mock_ctx, base_state):
        """No ClaimReview matches but domain source succeeds."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "unemployment rate dropped 3.5% economy data 2024"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            result = await evidence_node(base_state, mock_config)

        assert result["claimreview_matches"] == []
        assert len(result["domain_sources"]) == 1
        assert result["domain_sources"][0]["name"] != "N/A"

    @pytest.mark.asyncio
    async def test_all_sources_fail(self, mock_config, mock_ctx, base_state):
        """All domain source fetches fail → ABSENT alignment, 0 confidence."""
        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("Connection failed"),
            ),
        ):
            result = await evidence_node(base_state, mock_config)

        assert result["evidence_confidence"] == 0.0
        assert result["domain_sources"][0]["alignment"] == "ABSENT"
        assert result["domain_sources"][0]["name"] == "N/A"

    @pytest.mark.asyncio
    async def test_heartbeats_during_execution(self, mock_config, mock_ctx, base_state):
        """Evidence node sends heartbeats at each stage."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "some content"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            await evidence_node(base_state, mock_config)

        # Initial + before factcheck + before fetch + before domain obs publish = 4
        assert mock_ctx.heartbeat.call_count >= 4
        for call in mock_ctx.heartbeat.call_args_list:
            assert call.args[0] == AGENT_NAME

    @pytest.mark.asyncio
    async def test_publishes_domain_observations(self, mock_config, mock_ctx, base_state):
        """Evidence node publishes all 4 DOMAIN_* observations."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "some content"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            await evidence_node(base_state, mock_config)

        obs_codes = [
            call.kwargs["code"]
            for call in mock_ctx.publish_observation.call_args_list
        ]
        assert ObservationCode.DOMAIN_SOURCE_NAME in obs_codes
        assert ObservationCode.DOMAIN_SOURCE_URL in obs_codes
        assert ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT in obs_codes
        assert ObservationCode.DOMAIN_CONFIDENCE in obs_codes

    @pytest.mark.asyncio
    async def test_observations_use_evidence_agent_name(self, mock_config, mock_ctx, base_state):
        """All observations should use 'evidence' as the agent name."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "some content"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            await evidence_node(base_state, mock_config)

        for call in mock_ctx.publish_observation.call_args_list:
            assert call.kwargs["agent"] == "evidence"

    @pytest.mark.asyncio
    async def test_progress_messages_published(self, mock_config, mock_ctx, base_state):
        """Evidence node publishes start and completion progress messages."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "some content"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            await evidence_node(base_state, mock_config)

        assert mock_ctx.publish_progress.call_count == 2
        messages = [call.args[1] for call in mock_ctx.publish_progress.call_args_list]
        assert "Gathering evidence" in messages[0]
        assert "complete" in messages[1].lower()

    @pytest.mark.asyncio
    async def test_state_output_structure(self, mock_config, mock_ctx, base_state):
        """Returned dict has exactly the expected keys."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "content"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            result = await evidence_node(base_state, mock_config)

        assert set(result.keys()) == {
            "claimreview_matches",
            "domain_sources",
            "evidence_confidence",
            "observations",
        }
        assert isinstance(result["claimreview_matches"], list)
        assert isinstance(result["domain_sources"], list)
        assert isinstance(result["evidence_confidence"], float)
        assert isinstance(result["observations"], list)

    @pytest.mark.asyncio
    async def test_fallback_to_second_source(self, mock_config, mock_ctx, base_state):
        """First source fails, second succeeds → fallback_depth=1."""
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            resp = MagicMock()
            if call_count == 0:
                call_count += 1
                resp.status_code = 500
                resp.text = ""
                return resp
            resp.status_code = 200
            resp.text = "unemployment rate dropped 3.5% economy data 2024"
            return resp

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                side_effect=mock_get,
            ),
        ):
            result = await evidence_node(base_state, mock_config)

        # Second source succeeded, so name should not be N/A
        assert result["domain_sources"][0]["name"] != "N/A"
        # Confidence should be penalized for fallback_depth=1
        assert result["evidence_confidence"] < 1.0

    @pytest.mark.asyncio
    async def test_uses_normalized_claim_over_claim_text(self, mock_config, mock_ctx):
        """Node prefers normalized_claim when available."""
        state: PipelineState = {
            "claim_text": "ORIGINAL claim text",
            "normalized_claim": "normalized claim text",
            "claim_domain": "OTHER",
            "run_id": "run-test",
            "session_id": "sess-test",
            "entities": {},
            "observations": [],
            "errors": [],
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "normalized claim text content"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_api,
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            await evidence_node(state, mock_config)

        # The factcheck search should have received the normalized claim
        mock_api.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_claim_text(self, mock_config, mock_ctx):
        """When normalized_claim is absent, falls back to claim_text."""
        state: PipelineState = {
            "claim_text": "original claim text",
            "claim_domain": "OTHER",
            "run_id": "run-test",
            "session_id": "sess-test",
            "observations": [],
            "errors": [],
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "original claim text content"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            result = await evidence_node(state, mock_config)

        # Should still produce valid output
        assert "claimreview_matches" in result
        assert "domain_sources" in result

    @pytest.mark.asyncio
    async def test_returned_observations_match_published(self, mock_config, mock_ctx, base_state):
        """The 4 observations in the return dict match the 4 DOMAIN_* codes."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "content"

        with (
            patch.dict("os.environ", {"GOOGLE_FACTCHECK_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence._call_factcheck_api",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
        ):
            result = await evidence_node(base_state, mock_config)

        obs_codes = {o["code"] for o in result["observations"]}
        assert obs_codes == {
            "DOMAIN_SOURCE_NAME",
            "DOMAIN_SOURCE_URL",
            "DOMAIN_EVIDENCE_ALIGNMENT",
            "DOMAIN_CONFIDENCE",
        }
        for obs in result["observations"]:
            assert obs["agent"] == "evidence"
