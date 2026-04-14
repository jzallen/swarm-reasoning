"""Unit tests for source-validator citation aggregation."""

from __future__ import annotations

import json

from swarm_reasoning.agents.source_validator.aggregator import CitationAggregator
from swarm_reasoning.agents.source_validator.convergence import ConvergenceAnalyzer
from swarm_reasoning.agents.source_validator.models import (
    Citation,
    ExtractedUrl,
    UrlAssociation,
    ValidationResult,
    ValidationStatus,
)


def _make_aggregator() -> CitationAggregator:
    return CitationAggregator(ConvergenceAnalyzer())


class TestCitationAggregation:
    def test_full_aggregation_5_agents(self):
        extracted = [
            ExtractedUrl(
                url="https://reuters.com/article",
                associations=[
                    UrlAssociation("coverage-left", "COVERAGE_TOP_SOURCE_URL", "Reuters")
                ],
            ),
            ExtractedUrl(
                url="https://apnews.com/article",
                associations=[UrlAssociation("coverage-center", "COVERAGE_TOP_SOURCE_URL", "AP")],
            ),
            ExtractedUrl(
                url="https://foxnews.com/article",
                associations=[
                    UrlAssociation("coverage-right", "COVERAGE_TOP_SOURCE_URL", "Fox News")
                ],
            ),
            ExtractedUrl(
                url="https://politifact.com/check",
                associations=[
                    UrlAssociation("evidence", "CLAIMREVIEW_URL", "PolitiFact")
                ],
            ),
            ExtractedUrl(
                url="https://cdc.gov/data",
                associations=[UrlAssociation("evidence", "DOMAIN_SOURCE_URL", "CDC")],
            ),
        ]
        validations = {
            "https://reuters.com/article": ValidationResult(
                "https://reuters.com/article", ValidationStatus.LIVE
            ),
            "https://apnews.com/article": ValidationResult(
                "https://apnews.com/article", ValidationStatus.LIVE
            ),
            "https://foxnews.com/article": ValidationResult(
                "https://foxnews.com/article", ValidationStatus.LIVE
            ),
            "https://politifact.com/check": ValidationResult(
                "https://politifact.com/check", ValidationStatus.LIVE
            ),
            "https://cdc.gov/data": ValidationResult("https://cdc.gov/data", ValidationStatus.LIVE),
        }

        analyzer = ConvergenceAnalyzer()
        groups = analyzer.get_convergence_groups(extracted)
        agg = _make_aggregator()
        citations = agg.aggregate(extracted, validations, groups)

        assert len(citations) == 5
        assert all(c.validation_status == "live" for c in citations)
        assert all(c.convergence_count == 1 for c in citations)

    def test_multi_agent_url_produces_multiple_citations(self):
        extracted = [
            ExtractedUrl(
                url="https://cdc.gov/data",
                associations=[
                    UrlAssociation("coverage-center", "COVERAGE_TOP_SOURCE_URL", "CDC"),
                    UrlAssociation("evidence", "DOMAIN_SOURCE_URL", "CDC"),
                ],
            ),
        ]
        validations = {
            "https://cdc.gov/data": ValidationResult("https://cdc.gov/data", ValidationStatus.LIVE),
        }

        analyzer = ConvergenceAnalyzer()
        groups = analyzer.get_convergence_groups(extracted)
        agg = _make_aggregator()
        citations = agg.aggregate(extracted, validations, groups)

        assert len(citations) == 2
        assert all(c.convergence_count == 2 for c in citations)
        agents = {c.agent for c in citations}
        assert agents == {"coverage-center", "evidence"}

    def test_mixed_validation_statuses(self):
        extracted = [
            ExtractedUrl(
                url="https://live.com", associations=[UrlAssociation("agent-a", "CODE_A", "Live")]
            ),
            ExtractedUrl(
                url="https://dead.com", associations=[UrlAssociation("agent-b", "CODE_B", "Dead")]
            ),
            ExtractedUrl(
                url="https://timeout.com",
                associations=[UrlAssociation("agent-c", "CODE_C", "Timeout")],
            ),
        ]
        validations = {
            "https://live.com": ValidationResult("https://live.com", ValidationStatus.LIVE),
            "https://dead.com": ValidationResult("https://dead.com", ValidationStatus.DEAD),
            "https://timeout.com": ValidationResult(
                "https://timeout.com", ValidationStatus.TIMEOUT
            ),
        }

        analyzer = ConvergenceAnalyzer()
        groups = analyzer.get_convergence_groups(extracted)
        agg = _make_aggregator()
        citations = agg.aggregate(extracted, validations, groups)

        status_map = {c.source_url: c.validation_status for c in citations}
        assert status_map["https://live.com"] == "live"
        assert status_map["https://dead.com"] == "dead"
        assert status_map["https://timeout.com"] == "timeout"


class TestMissingValidation:
    def test_missing_validation_uses_not_validated(self):
        extracted = [
            ExtractedUrl(
                url="https://example.com",
                associations=[UrlAssociation("agent-a", "CODE_A", "Example")],
            ),
        ]
        validations: dict[str, ValidationResult] = {}  # No validation result

        analyzer = ConvergenceAnalyzer()
        groups = analyzer.get_convergence_groups(extracted)
        agg = _make_aggregator()
        citations = agg.aggregate(extracted, validations, groups)

        assert len(citations) == 1
        assert citations[0].validation_status == "not-validated"


class TestCitationSorting:
    def test_sorted_by_agent_then_code(self):
        extracted = [
            ExtractedUrl(
                url="https://z.com",
                associations=[UrlAssociation("coverage-right", "COVERAGE_TOP_SOURCE_URL", "Z")],
            ),
            ExtractedUrl(
                url="https://a.com",
                associations=[UrlAssociation("evidence", "CLAIMREVIEW_URL", "A")],
            ),
            ExtractedUrl(
                url="https://m.com",
                associations=[UrlAssociation("evidence", "DOMAIN_SOURCE_URL", "M")],
            ),
        ]
        validations = {
            "https://z.com": ValidationResult("https://z.com", ValidationStatus.LIVE),
            "https://a.com": ValidationResult("https://a.com", ValidationStatus.LIVE),
            "https://m.com": ValidationResult("https://m.com", ValidationStatus.LIVE),
        }

        analyzer = ConvergenceAnalyzer()
        groups = analyzer.get_convergence_groups(extracted)
        agg = _make_aggregator()
        citations = agg.aggregate(extracted, validations, groups)

        assert [c.agent for c in citations] == [
            "coverage-right",
            "evidence",
            "evidence",
        ]


class TestCitationJsonSerialization:
    def test_json_roundtrip(self):
        citations = [
            Citation(
                "https://cdc.gov/data", "CDC", "evidence", "DOMAIN_SOURCE_URL", "live", 2
            ),
            Citation(
                "https://reuters.com/article",
                "Reuters",
                "coverage-left",
                "COVERAGE_TOP_SOURCE_URL",
                "live",
                1,
            ),
        ]
        json_str = CitationAggregator.to_citation_list_json(citations)
        data = json.loads(json_str)
        assert len(data) == 2
        assert data[0]["sourceUrl"] == "https://cdc.gov/data"
        assert data[0]["validationStatus"] == "live"
        assert data[0]["convergenceCount"] == 2

    def test_empty_list_json(self):
        json_str = CitationAggregator.to_citation_list_json([])
        data = json.loads(json_str)
        assert data == []

    def test_json_exceeds_200_chars(self):
        """TX observation values must exceed 200 chars."""
        json_str = CitationAggregator.to_citation_list_json([])
        assert len(json_str) > 200

    def test_json_has_all_fields(self):
        citations = [
            Citation("https://example.com", "Example", "agent-a", "CODE_A", "live", 1),
        ]
        json_str = CitationAggregator.to_citation_list_json(citations)
        data = json.loads(json_str)
        entry = data[0]
        assert set(entry.keys()) == {
            "sourceUrl",
            "sourceName",
            "agent",
            "observationCode",
            "validationStatus",
            "convergenceCount",
        }


class TestCitationModel:
    def test_to_dict(self):
        c = Citation("https://cdc.gov", "CDC", "evidence", "DOMAIN_SOURCE_URL", "live", 2)
        d = c.to_dict()
        assert d == {
            "sourceUrl": "https://cdc.gov",
            "sourceName": "CDC",
            "agent": "evidence",
            "observationCode": "DOMAIN_SOURCE_URL",
            "validationStatus": "live",
            "convergenceCount": 2,
        }

    def test_validation_status_enum_to_citation(self):
        assert ValidationStatus.LIVE.to_citation_status() == "live"
        assert ValidationStatus.DEAD.to_citation_status() == "dead"
        assert ValidationStatus.REDIRECT.to_citation_status() == "redirect"
        assert ValidationStatus.SOFT404.to_citation_status() == "soft-404"
        assert ValidationStatus.TIMEOUT.to_citation_status() == "timeout"

    def test_validation_status_enum_to_cwe(self):
        assert ValidationStatus.LIVE.to_cwe() == "LIVE^Live^FCK"
        assert ValidationStatus.DEAD.to_cwe() == "DEAD^Dead^FCK"
        assert ValidationStatus.REDIRECT.to_cwe() == "REDIRECT^Redirect^FCK"
        assert ValidationStatus.SOFT404.to_cwe() == "SOFT404^Soft 404^FCK"
        assert ValidationStatus.TIMEOUT.to_cwe() == "TIMEOUT^Timeout^FCK"
