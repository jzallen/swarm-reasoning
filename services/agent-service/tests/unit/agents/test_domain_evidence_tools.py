"""Unit tests for domain-evidence @tool definitions."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from swarm_reasoning.agents.domain_evidence.tools import (
    DOMAIN_EVIDENCE_TOOLS,
    check_content_relevance,
    compute_evidence_confidence,
    derive_search_query,
    fetch_source_content,
    format_source_url,
    lookup_domain_sources,
    score_claim_alignment,
)


# ---- lookup_domain_sources ----


class TestLookupDomainSources:
    def test_healthcare_returns_sources(self):
        result = lookup_domain_sources.invoke({"domain": "HEALTHCARE"})
        sources = json.loads(result)
        assert len(sources) >= 1
        assert sources[0]["name"] == "CDC"
        assert "{query}" in sources[0]["url_template"]

    def test_case_insensitive(self):
        result = lookup_domain_sources.invoke({"domain": "healthcare"})
        sources = json.loads(result)
        assert sources[0]["name"] == "CDC"

    def test_unknown_domain_falls_back_to_other(self):
        result = lookup_domain_sources.invoke({"domain": "ASTROLOGY"})
        sources = json.loads(result)
        assert len(sources) >= 1
        # OTHER has Google as fallback
        assert any("Google" in s["name"] for s in sources)

    def test_economics_returns_sources(self):
        result = lookup_domain_sources.invoke({"domain": "ECONOMICS"})
        sources = json.loads(result)
        names = [s["name"] for s in sources]
        assert "SEC EDGAR" in names

    def test_all_domains_return_valid_json(self):
        for domain in ["HEALTHCARE", "ECONOMICS", "POLICY", "SCIENCE", "ELECTION", "CRIME", "OTHER"]:
            result = lookup_domain_sources.invoke({"domain": domain})
            sources = json.loads(result)
            assert isinstance(sources, list)
            for source in sources:
                assert "name" in source
                assert "url_template" in source


# ---- fetch_source_content ----


class TestFetchSourceContent:
    @pytest.mark.asyncio
    async def test_success_returns_content(self):
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.text = "CDC reports vaccine efficacy data"

        with patch(
            "swarm_reasoning.agents.domain_evidence.tools.resilient_get",
            return_value=mock_resp,
        ):
            result = await fetch_source_content.ainvoke(
                {"url": "https://search.cdc.gov/search?query=vaccines"}
            )

        assert "CDC reports" in result
        assert not result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_truncates_long_content(self):
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.text = "x" * 5000

        with patch(
            "swarm_reasoning.agents.domain_evidence.tools.resilient_get",
            return_value=mock_resp,
        ):
            result = await fetch_source_content.ainvoke({"url": "https://example.com"})

        assert len(result) == 2000

    @pytest.mark.asyncio
    async def test_http_error_returns_error_string(self):
        mock_resp = AsyncMock()
        mock_resp.status_code = 404

        with patch(
            "swarm_reasoning.agents.domain_evidence.tools.resilient_get",
            return_value=mock_resp,
        ):
            result = await fetch_source_content.ainvoke({"url": "https://example.com/missing"})

        assert result.startswith("ERROR:")
        assert "404" in result

    @pytest.mark.asyncio
    async def test_connection_error_returns_error_string(self):
        with patch(
            "swarm_reasoning.agents.domain_evidence.tools.resilient_get",
            side_effect=ConnectionError("DNS resolution failed"),
        ):
            result = await fetch_source_content.ainvoke({"url": "https://bad.example.com"})

        assert result.startswith("ERROR:")
        assert "Failed to fetch" in result


# ---- derive_search_query ----


class TestDeriveSearchQuery:
    def test_basic_claim(self):
        result = derive_search_query.invoke(
            {"normalized_claim": "vaccines reduced hospitalizations"}
        )
        assert "vaccines" in result
        assert "reduced" in result
        assert "hospitalizations" in result

    def test_includes_entities(self):
        result = derive_search_query.invoke(
            {
                "normalized_claim": "approved vaccine for children",
                "organizations": "FDA, Pfizer",
            }
        )
        assert "FDA" in result
        assert "Pfizer" in result

    def test_includes_statistics(self):
        result = derive_search_query.invoke(
            {
                "normalized_claim": "unemployment rate fell",
                "statistics": "3.4%",
            }
        )
        assert "3.4%" in result

    def test_truncates_to_80_chars(self):
        result = derive_search_query.invoke(
            {"normalized_claim": "word " * 100}
        )
        assert len(result) <= 80

    def test_filters_stop_words(self):
        result = derive_search_query.invoke(
            {"normalized_claim": "the vaccines are very effective"}
        )
        # "the", "are", "very" are stop words
        assert "the" not in result.lower().split()
        assert "vaccines" in result

    def test_empty_entities(self):
        result = derive_search_query.invoke(
            {
                "normalized_claim": "test claim",
                "persons": "",
                "organizations": "",
            }
        )
        assert "claim" in result
        # No entities prepended when empty
        assert result == "test claim"


# ---- format_source_url ----


class TestFormatSourceUrl:
    def test_encodes_query(self):
        result = format_source_url.invoke(
            {
                "url_template": "https://example.com/search?q={query}",
                "query": "covid vaccines 2023",
            }
        )
        assert "covid+vaccines+2023" in result
        assert "{query}" not in result

    def test_special_characters(self):
        result = format_source_url.invoke(
            {
                "url_template": "https://example.com/search?q={query}",
                "query": "GDP growth 3.4% Q1",
            }
        )
        assert "{query}" not in result
        assert "example.com" in result


# ---- check_content_relevance ----


class TestCheckContentRelevance:
    def test_relevant_by_entity(self):
        result = check_content_relevance.invoke(
            {
                "content": "The CDC has issued new guidance on vaccination schedules",
                "normalized_claim": "vaccines reduced hospitalizations",
                "organizations": "CDC",
            }
        )
        assert result == "RELEVANT"

    def test_relevant_by_keywords(self):
        result = check_content_relevance.invoke(
            {
                "content": "vaccines reduced hospitalizations by 90 percent",
                "normalized_claim": "vaccines reduced hospitalizations by 90 percent",
            }
        )
        assert result == "RELEVANT"

    def test_not_relevant(self):
        result = check_content_relevance.invoke(
            {
                "content": "weather forecast shows sunny skies this weekend",
                "normalized_claim": "vaccines reduced hospitalizations",
            }
        )
        assert result == "NOT_RELEVANT"

    def test_empty_content(self):
        result = check_content_relevance.invoke(
            {
                "content": "",
                "normalized_claim": "test claim",
            }
        )
        assert result == "NOT_RELEVANT"

    def test_person_entity_match(self):
        result = check_content_relevance.invoke(
            {
                "content": "Dr. Fauci spoke about pandemic preparedness",
                "normalized_claim": "pandemic response was effective",
                "persons": "Dr. Fauci",
            }
        )
        assert result == "RELEVANT"


# ---- score_claim_alignment ----


class TestScoreClaimAlignment:
    def test_supports_high_overlap_no_negation(self):
        result = score_claim_alignment.invoke(
            {
                "content": "vaccines reduced hospitalizations by 90 percent according to data",
                "normalized_claim": "vaccines reduced hospitalizations by 90 percent",
            }
        )
        assert "SUPPORTS" in result
        assert "^" in result  # CWE format

    def test_contradicts_high_overlap_with_negation(self):
        result = score_claim_alignment.invoke(
            {
                "content": "no evidence that vaccines reduced hospitalizations by 90 percent",
                "normalized_claim": "vaccines reduced hospitalizations by 90 percent",
            }
        )
        assert "CONTRADICTS" in result

    def test_absent_low_overlap(self):
        result = score_claim_alignment.invoke(
            {
                "content": "weather forecast for this weekend shows sunny skies",
                "normalized_claim": "unemployment rate fell dramatically last quarter",
            }
        )
        assert "ABSENT" in result

    def test_empty_content_absent(self):
        result = score_claim_alignment.invoke(
            {
                "content": "",
                "normalized_claim": "test claim",
            }
        )
        assert "ABSENT" in result

    def test_cwe_format(self):
        result = score_claim_alignment.invoke(
            {
                "content": "vaccines work well",
                "normalized_claim": "vaccines work well",
            }
        )
        parts = result.split("^")
        assert len(parts) == 3
        assert parts[2] == "FCK"


# ---- compute_evidence_confidence ----


class TestComputeEvidenceConfidence:
    def test_full_confidence_primary_source(self):
        result = compute_evidence_confidence.invoke(
            {"alignment": "SUPPORTS^Supports Claim^FCK"}
        )
        assert result == "1.00"

    def test_fallback_penalty(self):
        result = compute_evidence_confidence.invoke(
            {"alignment": "SUPPORTS^Supports Claim^FCK", "fallback_depth": 2}
        )
        assert result == "0.80"

    def test_old_source_penalty(self):
        result = compute_evidence_confidence.invoke(
            {"alignment": "SUPPORTS^Supports Claim^FCK", "source_is_old": True}
        )
        assert result == "0.85"

    def test_indirect_source_penalty(self):
        result = compute_evidence_confidence.invoke(
            {"alignment": "SUPPORTS^Supports Claim^FCK", "is_indirect": True}
        )
        assert result == "0.80"

    def test_partial_alignment_penalty(self):
        result = compute_evidence_confidence.invoke(
            {"alignment": "PARTIAL^Partially Supports^FCK"}
        )
        assert result == "0.90"

    def test_absent_always_zero(self):
        result = compute_evidence_confidence.invoke(
            {"alignment": "ABSENT^No Evidence Found^FCK"}
        )
        assert result == "0.00"

    def test_combined_penalties(self):
        result = compute_evidence_confidence.invoke(
            {"alignment": "PARTIAL^Partially Supports^FCK", "fallback_depth": 2}
        )
        assert result == "0.70"

    def test_floor_at_0_10(self):
        result = compute_evidence_confidence.invoke(
            {
                "alignment": "PARTIAL^Partially Supports^FCK",
                "fallback_depth": 5,
                "source_is_old": True,
                "is_indirect": True,
            }
        )
        assert result == "0.10"


# ---- DOMAIN_EVIDENCE_TOOLS list ----


class TestToolsList:
    def test_contains_all_tools(self):
        assert len(DOMAIN_EVIDENCE_TOOLS) == 7

    def test_all_have_names(self):
        names = [t.name for t in DOMAIN_EVIDENCE_TOOLS]
        assert "lookup_domain_sources" in names
        assert "fetch_source_content" in names
        assert "derive_search_query" in names
        assert "format_source_url" in names
        assert "check_content_relevance" in names
        assert "score_claim_alignment" in names
        assert "compute_evidence_confidence" in names

    def test_all_have_descriptions(self):
        for t in DOMAIN_EVIDENCE_TOOLS:
            assert t.description, f"Tool {t.name} has no description"
