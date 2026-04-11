"""Unit tests for source-validator convergence scoring."""

from __future__ import annotations

from swarm_reasoning.agents.source_validator.convergence import (
    ConvergenceAnalyzer,
    normalize_url,
)
from swarm_reasoning.agents.source_validator.models import ExtractedUrl, UrlAssociation


class TestNormalizeUrl:
    def test_strips_www(self):
        assert normalize_url("https://www.cdc.gov/covid/data") == "https://cdc.gov/covid/data"

    def test_removes_query_params(self):
        assert normalize_url("https://cdc.gov/covid/data?page=1") == "https://cdc.gov/covid/data"

    def test_removes_fragment(self):
        assert normalize_url("https://cdc.gov/covid/data#section2") == "https://cdc.gov/covid/data"

    def test_removes_trailing_slash(self):
        assert normalize_url("https://cdc.gov/covid/data/") == "https://cdc.gov/covid/data"

    def test_lowercases_scheme_and_netloc(self):
        assert normalize_url("HTTPS://WWW.CDC.GOV/covid/data") == "https://cdc.gov/covid/data"

    def test_combined_normalization(self):
        result = normalize_url("https://www.cdc.gov/covid/data/?page=1#section2")
        assert result == "https://cdc.gov/covid/data"

    def test_different_paths_stay_distinct(self):
        url1 = normalize_url("https://reuters.com/world/article1")
        url2 = normalize_url("https://reuters.com/business/article2")
        assert url1 != url2

    def test_preserves_non_standard_port(self):
        result = normalize_url("https://example.com:8443/api/data")
        assert result == "https://example.com:8443/api/data"


class TestConvergenceScore:
    def test_no_convergence_all_unique(self):
        extracted = [
            ExtractedUrl(
                url="https://a.com/1", associations=[UrlAssociation("agent-a", "CODE_A", "A")]
            ),
            ExtractedUrl(
                url="https://b.com/2", associations=[UrlAssociation("agent-b", "CODE_B", "B")]
            ),
            ExtractedUrl(
                url="https://c.com/3", associations=[UrlAssociation("agent-c", "CODE_C", "C")]
            ),
            ExtractedUrl(
                url="https://d.com/4", associations=[UrlAssociation("agent-d", "CODE_D", "D")]
            ),
            ExtractedUrl(
                url="https://e.com/5", associations=[UrlAssociation("agent-e", "CODE_E", "E")]
            ),
        ]
        analyzer = ConvergenceAnalyzer()
        assert analyzer.compute_convergence_score(extracted) == 0.0

    def test_partial_convergence(self):
        extracted = [
            # URL 1: cited by 2 agents (converging)
            ExtractedUrl(
                url="https://cdc.gov/data",
                associations=[
                    UrlAssociation("coverage-center", "COVERAGE_TOP_SOURCE_URL", "CDC"),
                    UrlAssociation("domain-evidence", "DOMAIN_SOURCE_URL", "CDC"),
                ],
            ),
            # URL 2: cited by 2 agents (converging)
            ExtractedUrl(
                url="https://reuters.com/article",
                associations=[
                    UrlAssociation("coverage-left", "COVERAGE_TOP_SOURCE_URL", "Reuters"),
                    UrlAssociation("claimreview-matcher", "CLAIMREVIEW_URL", "Reuters"),
                ],
            ),
            # URL 3: cited by 1 agent (not converging)
            ExtractedUrl(
                url="https://foxnews.com/article",
                associations=[
                    UrlAssociation("coverage-right", "COVERAGE_TOP_SOURCE_URL", "Fox News")
                ],
            ),
            # URL 4: cited by 1 agent (not converging)
            ExtractedUrl(
                url="https://apnews.com/article",
                associations=[UrlAssociation("coverage-center", "COVERAGE_TOP_SOURCE_URL", "AP")],
            ),
        ]
        analyzer = ConvergenceAnalyzer()
        # 2 converging out of 4 unique = 0.5
        assert analyzer.compute_convergence_score(extracted) == 0.5

    def test_full_convergence(self):
        extracted = [
            ExtractedUrl(
                url="https://a.com/1",
                associations=[
                    UrlAssociation("agent-a", "CODE_A", "A"),
                    UrlAssociation("agent-b", "CODE_B", "A"),
                ],
            ),
            ExtractedUrl(
                url="https://b.com/2",
                associations=[
                    UrlAssociation("agent-c", "CODE_C", "B"),
                    UrlAssociation("agent-d", "CODE_D", "B"),
                ],
            ),
            ExtractedUrl(
                url="https://c.com/3",
                associations=[
                    UrlAssociation("agent-e", "CODE_E", "C"),
                    UrlAssociation("agent-f", "CODE_F", "C"),
                ],
            ),
        ]
        analyzer = ConvergenceAnalyzer()
        assert analyzer.compute_convergence_score(extracted) == 1.0

    def test_empty_list(self):
        analyzer = ConvergenceAnalyzer()
        assert analyzer.compute_convergence_score([]) == 0.0

    def test_single_url_single_agent(self):
        extracted = [
            ExtractedUrl(
                url="https://a.com/1", associations=[UrlAssociation("agent-a", "CODE_A", "A")]
            ),
        ]
        analyzer = ConvergenceAnalyzer()
        assert analyzer.compute_convergence_score(extracted) == 0.0

    def test_normalized_convergence(self):
        """URLs that differ only in www/query/fragment should converge."""
        extracted = [
            ExtractedUrl(
                url="https://www.cdc.gov/covid/data/?page=1",
                associations=[UrlAssociation("coverage-left", "COVERAGE_TOP_SOURCE_URL", "CDC")],
            ),
            ExtractedUrl(
                url="https://cdc.gov/covid/data/#section2",
                associations=[UrlAssociation("domain-evidence", "DOMAIN_SOURCE_URL", "CDC")],
            ),
        ]
        analyzer = ConvergenceAnalyzer()
        # 2 extracted URLs normalize to 1 unique URL cited by 2 agents = 1.0
        assert analyzer.compute_convergence_score(extracted) == 1.0


class TestConvergenceCount:
    def test_convergence_count_for_multi_agent_url(self):
        extracted = [
            ExtractedUrl(
                url="https://cdc.gov/data",
                associations=[
                    UrlAssociation("coverage-center", "COVERAGE_TOP_SOURCE_URL", "CDC"),
                    UrlAssociation("domain-evidence", "DOMAIN_SOURCE_URL", "CDC"),
                    UrlAssociation("claimreview-matcher", "CLAIMREVIEW_URL", "CDC"),
                ],
            ),
        ]
        analyzer = ConvergenceAnalyzer()
        groups = analyzer.get_convergence_groups(extracted)
        count = analyzer.get_convergence_count("https://cdc.gov/data", groups)
        assert count == 3

    def test_convergence_count_single_agent(self):
        extracted = [
            ExtractedUrl(
                url="https://reuters.com/article",
                associations=[
                    UrlAssociation("coverage-left", "COVERAGE_TOP_SOURCE_URL", "Reuters")
                ],
            ),
        ]
        analyzer = ConvergenceAnalyzer()
        groups = analyzer.get_convergence_groups(extracted)
        count = analyzer.get_convergence_count("https://reuters.com/article", groups)
        assert count == 1
