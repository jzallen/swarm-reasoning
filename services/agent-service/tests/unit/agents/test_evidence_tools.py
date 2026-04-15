"""Unit tests for evidence agent tools.

Tests cover the four tool modules:
- search_factchecks: API query building, scoring, threshold, error handling
- lookup_domain_sources: Domain routing, query derivation, URL formatting
- fetch_source_content: HTTP fetching, error handling, content relevance
- score_evidence: Alignment scoring, confidence computation with penalties
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from swarm_reasoning.agents.evidence.tools import (
    MATCH_THRESHOLD,
    Alignment,
    AlignmentResult,
    DomainSource,
    FactCheckResult,
    FetchResult,
    check_content_relevance,
    compute_evidence_confidence,
    derive_search_query,
    fetch_source_content,
    format_source_url,
    lookup_domain_sources,
    score_claim_alignment,
    search_factchecks,
)

# ---------------------------------------------------------------------------
# search_factchecks
# ---------------------------------------------------------------------------


class TestSearchFactchecks:
    """Tests for the ClaimReview API search function."""

    async def test_missing_api_key_returns_error(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_FACTCHECK_API_KEY", raising=False)
        result = await search_factchecks("some claim")
        assert result.matched is False
        assert result.error is not None
        assert "API_KEY" in result.error

    async def test_api_call_failure_returns_error(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_FACTCHECK_API_KEY", "test-key")
        with patch(
            "swarm_reasoning.agents.evidence.tools.search_factchecks._call_api",
            side_effect=Exception("network error"),
        ):
            result = await search_factchecks("some claim")
        assert result.matched is False
        assert result.error is not None
        assert "network error" in result.error

    async def test_no_results_returns_no_match(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_FACTCHECK_API_KEY", "test-key")
        with patch(
            "swarm_reasoning.agents.evidence.tools.search_factchecks._call_api",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await search_factchecks("some claim")
        assert result.matched is False
        assert result.error is None
        assert result.score == 0.0

    async def test_below_threshold_returns_no_match(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_FACTCHECK_API_KEY", "test-key")
        low_match = [
            {
                "text": "completely unrelated claim text",
                "claimReview": [
                    {
                        "title": "completely different review",
                        "textualRating": "True",
                        "publisher": {"name": "Snopes"},
                        "url": "https://snopes.com/1",
                    }
                ],
            }
        ]
        with patch(
            "swarm_reasoning.agents.evidence.tools.search_factchecks._call_api",
            new_callable=AsyncMock,
            return_value=low_match,
        ):
            result = await search_factchecks("the unemployment rate is 3.5%")
        assert result.matched is False
        assert result.score < MATCH_THRESHOLD

    async def test_above_threshold_returns_match(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_FACTCHECK_API_KEY", "test-key")
        good_match = [
            {
                "text": "the unemployment rate dropped to 3.5%",
                "claimReview": [
                    {
                        "title": "the unemployment rate dropped to 3.5%",
                        "textualRating": "Mostly True",
                        "publisher": {"name": "PolitiFact"},
                        "url": "https://politifact.com/1",
                    }
                ],
            }
        ]
        with patch(
            "swarm_reasoning.agents.evidence.tools.search_factchecks._call_api",
            new_callable=AsyncMock,
            return_value=good_match,
        ):
            result = await search_factchecks(
                "the unemployment rate dropped to 3.5%",
                persons=["Joe Biden"],
            )
        assert result.matched is True
        assert result.score >= MATCH_THRESHOLD
        assert result.rating == "Mostly True"
        assert result.source == "PolitiFact"
        assert result.url == "https://politifact.com/1"

    async def test_entities_included_in_query(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_FACTCHECK_API_KEY", "test-key")
        with patch(
            "swarm_reasoning.agents.evidence.tools.search_factchecks._call_api",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_api:
            await search_factchecks(
                "vaccine rates", persons=["Fauci"], organizations=["CDC"],
            )
        query = mock_api.call_args.args[0]
        assert "Fauci" in query
        assert "CDC" in query

    async def test_result_is_factcheck_result(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_FACTCHECK_API_KEY", raising=False)
        result = await search_factchecks("test")
        assert isinstance(result, FactCheckResult)


# ---------------------------------------------------------------------------
# lookup_domain_sources
# ---------------------------------------------------------------------------


class TestLookupDomainSources:
    """Tests for the domain routing table lookup."""

    def test_healthcare_returns_cdc_who(self):
        sources = lookup_domain_sources("HEALTHCARE")
        names = [s.name for s in sources]
        assert "CDC" in names
        assert "WHO" in names

    def test_economics_returns_sec_fred_bls(self):
        sources = lookup_domain_sources("ECONOMICS")
        names = [s.name for s in sources]
        assert "SEC EDGAR" in names
        assert "FRED" in names
        assert "BLS" in names

    def test_unknown_domain_falls_back_to_other(self):
        sources = lookup_domain_sources("NONEXISTENT")
        assert len(sources) >= 1
        # OTHER has Google (.gov/.edu)
        names = [s.name for s in sources]
        assert any("Google" in n for n in names)

    def test_case_insensitive(self):
        upper = lookup_domain_sources("HEALTHCARE")
        lower = lookup_domain_sources("healthcare")
        assert [s.name for s in upper] == [s.name for s in lower]

    def test_returns_domain_source_objects(self):
        sources = lookup_domain_sources("SCIENCE")
        for s in sources:
            assert isinstance(s, DomainSource)
            assert s.name
            assert s.url_template

    def test_url_templates_have_query_placeholder(self):
        domains = [
            "HEALTHCARE", "ECONOMICS", "POLICY", "SCIENCE",
            "ELECTION", "CRIME", "OTHER",
        ]
        for domain in domains:
            sources = lookup_domain_sources(domain)
            for s in sources:
                assert "{query}" in s.url_template


# ---------------------------------------------------------------------------
# derive_search_query
# ---------------------------------------------------------------------------


class TestDeriveSearchQuery:
    """Tests for search query derivation from claim context."""

    def test_basic_query(self):
        result = derive_search_query("the unemployment rate dropped")
        assert "unemployment" in result
        assert "rate" in result
        assert "dropped" in result

    def test_stop_words_removed(self):
        result = derive_search_query("the rate is very high")
        assert "the" not in result.split()
        assert "is" not in result.split()
        assert "very" not in result.split()

    def test_entities_prepended(self):
        result = derive_search_query(
            "vaccine rates", persons=["Fauci"], organizations=["WHO"],
        )
        assert result.startswith("Fauci")
        assert "WHO" in result

    def test_statistics_appended(self):
        result = derive_search_query("rates dropped", statistics=["3.5%"])
        assert "3.5%" in result

    def test_dates_appended(self):
        result = derive_search_query("rates dropped", dates=["2024"])
        assert "2024" in result

    def test_truncated_to_80_chars(self):
        long_claim = " ".join([f"word{i}" for i in range(100)])
        result = derive_search_query(long_claim)
        assert len(result) <= 80

    def test_truncation_at_word_boundary(self):
        long_claim = " ".join([f"word{i}" for i in range(100)])
        result = derive_search_query(long_claim)
        # Should not cut mid-word
        assert not result.endswith("wor")


# ---------------------------------------------------------------------------
# format_source_url
# ---------------------------------------------------------------------------


class TestFormatSourceUrl:
    """Tests for URL template formatting."""

    def test_substitutes_query(self):
        url = format_source_url("https://example.com?q={query}", "test query")
        assert "test+query" in url

    def test_url_encodes_special_chars(self):
        url = format_source_url("https://example.com?q={query}", "3.5% rate")
        assert "3.5%25" in url  # % is encoded

    def test_preserves_template_structure(self):
        url = format_source_url("https://cdc.gov/search?query={query}", "vaccine")
        assert url.startswith("https://cdc.gov/search?query=")
        assert "vaccine" in url


# ---------------------------------------------------------------------------
# fetch_source_content
# ---------------------------------------------------------------------------


class TestFetchSourceContent:
    """Tests for HTTP content fetching."""

    async def test_successful_fetch(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Content about vaccines and public health."
        with patch(
            "swarm_reasoning.agents.evidence.tools.fetch_source_content.resilient_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await fetch_source_content("https://cdc.gov/search?q=test")
        assert result.content == "Content about vaccines and public health."
        assert result.error is None

    async def test_truncates_long_content(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "x" * 5000
        with patch(
            "swarm_reasoning.agents.evidence.tools.fetch_source_content.resilient_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await fetch_source_content("https://example.com")
        assert len(result.content) == 2000

    async def test_http_error_returns_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 404
        with patch(
            "swarm_reasoning.agents.evidence.tools.fetch_source_content.resilient_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await fetch_source_content("https://example.com/missing")
        assert result.error is not None
        assert "404" in result.error
        assert result.content == ""

    async def test_network_exception_returns_error(self):
        with patch(
            "swarm_reasoning.agents.evidence.tools.fetch_source_content.resilient_get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await fetch_source_content("https://example.com")
        assert result.error is not None
        assert result.content == ""

    async def test_returns_fetch_result(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "content"
        with patch(
            "swarm_reasoning.agents.evidence.tools.fetch_source_content.resilient_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await fetch_source_content("https://example.com")
        assert isinstance(result, FetchResult)


# ---------------------------------------------------------------------------
# check_content_relevance
# ---------------------------------------------------------------------------


class TestCheckContentRelevance:
    """Tests for content relevance checking."""

    def test_relevant_by_entity_presence(self):
        content = "Joe Biden announced the new infrastructure plan."
        result = check_content_relevance(
            content, "infrastructure plan", persons=["Joe Biden"],
        )
        assert result is True

    def test_relevant_by_keyword_overlap(self):
        content = "The unemployment rate dropped significantly in the latest report."
        assert check_content_relevance(content, "unemployment rate dropped") is True

    def test_irrelevant_content(self):
        content = "Weather forecast for tomorrow shows sunny skies."
        assert check_content_relevance(content, "unemployment rate dropped") is False

    def test_empty_content_is_irrelevant(self):
        assert check_content_relevance("", "some claim") is False

    def test_organization_entity_presence(self):
        content = "The CDC released new guidelines for testing."
        assert check_content_relevance(
            content, "testing guidelines", organizations=["CDC"],
        ) is True


# ---------------------------------------------------------------------------
# score_claim_alignment
# ---------------------------------------------------------------------------


class TestScoreClaimAlignment:
    """Tests for claim-content alignment scoring."""

    def test_supports_alignment(self):
        content = "The unemployment rate dropped to 3.5% last quarter according to BLS data."
        result = score_claim_alignment(content, "unemployment rate dropped 3.5%")
        assert result.alignment == Alignment.SUPPORTS

    def test_contradicts_alignment(self):
        content = (
            "The claim is false. The unemployment rate did not "
            "drop to 3.5%. This has been debunked."
        )
        result = score_claim_alignment(content, "unemployment rate dropped 3.5%")
        assert result.alignment == Alignment.CONTRADICTS

    def test_partial_alignment(self):
        content = "Employment figures changed moderately."
        result = score_claim_alignment(content, "unemployment rate dropped significantly to 3.5%")
        assert result.alignment in (Alignment.PARTIAL, Alignment.ABSENT)

    def test_absent_with_empty_content(self):
        result = score_claim_alignment("", "some claim")
        assert result.alignment == Alignment.ABSENT
        assert "No Evidence" in result.description

    def test_absent_with_no_keyword_overlap(self):
        content = "Weather is nice today with clear skies and mild temperatures."
        result = score_claim_alignment(content, "unemployment rate dropped 3.5%")
        assert result.alignment == Alignment.ABSENT

    def test_returns_alignment_result(self):
        result = score_claim_alignment("some content", "some claim")
        assert isinstance(result, AlignmentResult)
        assert isinstance(result.alignment, Alignment)
        assert isinstance(result.description, str)


# ---------------------------------------------------------------------------
# compute_evidence_confidence
# ---------------------------------------------------------------------------


class TestComputeEvidenceConfidence:
    """Tests for evidence confidence computation."""

    def test_absent_returns_zero(self):
        assert compute_evidence_confidence(Alignment.ABSENT) == 0.0

    def test_supports_returns_high_confidence(self):
        confidence = compute_evidence_confidence(Alignment.SUPPORTS)
        assert confidence == 1.0

    def test_partial_penalized(self):
        confidence = compute_evidence_confidence(Alignment.PARTIAL)
        assert confidence < 1.0
        assert confidence == 0.9  # 1.0 - 0.10 for partial

    def test_fallback_depth_penalty(self):
        base = compute_evidence_confidence(Alignment.SUPPORTS, fallback_depth=0)
        with_fallback = compute_evidence_confidence(Alignment.SUPPORTS, fallback_depth=2)
        assert with_fallback < base
        assert with_fallback == 0.8  # 1.0 - 0.10 * 2

    def test_old_source_penalty(self):
        fresh = compute_evidence_confidence(Alignment.SUPPORTS, source_is_old=False)
        old = compute_evidence_confidence(Alignment.SUPPORTS, source_is_old=True)
        assert old < fresh
        assert old == 0.85  # 1.0 - 0.15

    def test_indirect_source_penalty(self):
        direct = compute_evidence_confidence(Alignment.SUPPORTS, is_indirect=False)
        indirect = compute_evidence_confidence(Alignment.SUPPORTS, is_indirect=True)
        assert indirect < direct
        assert indirect == 0.80  # 1.0 - 0.20

    def test_combined_penalties(self):
        confidence = compute_evidence_confidence(
            Alignment.PARTIAL, fallback_depth=1, source_is_old=True, is_indirect=True,
        )
        # 1.0 - 0.10(fallback) - 0.15(old) - 0.20(indirect) - 0.10(partial) = 0.45
        assert confidence == pytest.approx(0.45)

    def test_minimum_confidence_floor(self):
        confidence = compute_evidence_confidence(
            Alignment.PARTIAL, fallback_depth=10, source_is_old=True, is_indirect=True,
        )
        assert confidence == 0.10  # Floor

    def test_contradicts_no_extra_penalty(self):
        # CONTRADICTS has same base as SUPPORTS (no partial penalty)
        confidence = compute_evidence_confidence(Alignment.CONTRADICTS)
        assert confidence == 1.0
