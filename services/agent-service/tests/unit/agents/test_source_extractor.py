"""Unit tests for source-validator link extraction."""

from __future__ import annotations

from swarm_reasoning.agents.source_validator.extractor import LinkExtractor


class TestLinkExtractorFullExtraction:
    def test_extracts_urls_from_5_agents(self):
        data = {
            "urls": [
                {
                    "url": "https://reuters.com/article/123",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Reuters",
                },
                {
                    "url": "https://apnews.com/article/456",
                    "agent": "coverage-center",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "AP",
                },
                {
                    "url": "https://foxnews.com/article/789",
                    "agent": "coverage-right",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Fox News",
                },
                {
                    "url": "https://www.politifact.com/factchecks/2023/test",
                    "agent": "evidence",
                    "code": "CLAIMREVIEW_URL",
                    "source_name": "PolitiFact",
                },
                {
                    "url": "https://www.cdc.gov/covid/data/",
                    "agent": "evidence",
                    "code": "DOMAIN_SOURCE_URL",
                    "source_name": "CDC",
                },
            ]
        }
        extractor = LinkExtractor()
        result = extractor.extract_urls(data)
        assert len(result) == 5
        agents = {eu.associations[0].agent for eu in result}
        assert agents == {
            "coverage-left",
            "coverage-center",
            "coverage-right",
            "evidence",
            "evidence",
        }

    def test_preserves_source_names(self):
        data = {
            "urls": [
                {
                    "url": "https://reuters.com/article/123",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Reuters",
                },
            ]
        }
        extractor = LinkExtractor()
        result = extractor.extract_urls(data)
        assert result[0].associations[0].source_name == "Reuters"


class TestLinkExtractorDeduplication:
    def test_deduplicates_same_url_from_two_agents(self):
        data = {
            "urls": [
                {
                    "url": "https://www.cdc.gov/covid/data/",
                    "agent": "coverage-center",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "CDC",
                },
                {
                    "url": "https://www.cdc.gov/covid/data/",
                    "agent": "evidence",
                    "code": "DOMAIN_SOURCE_URL",
                    "source_name": "CDC",
                },
            ]
        }
        extractor = LinkExtractor()
        result = extractor.extract_urls(data)
        assert len(result) == 1
        assert len(result[0].associations) == 2
        agents = {a.agent for a in result[0].associations}
        assert agents == {"coverage-center", "evidence"}


class TestLinkExtractorEmpty:
    def test_empty_urls_list(self):
        extractor = LinkExtractor()
        result = extractor.extract_urls({"urls": []})
        assert result == []

    def test_missing_urls_key(self):
        extractor = LinkExtractor()
        result = extractor.extract_urls({})
        assert result == []

    def test_empty_dict(self):
        extractor = LinkExtractor()
        result = extractor.extract_urls({})
        assert result == []


class TestLinkExtractorFiltering:
    def test_rejects_malformed_url(self):
        data = {
            "urls": [
                {
                    "url": "not-a-url",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Bad",
                },
            ]
        }
        extractor = LinkExtractor()
        result = extractor.extract_urls(data)
        assert result == []

    def test_rejects_localhost(self):
        data = {
            "urls": [
                {
                    "url": "http://localhost:8080/test",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Local",
                },
            ]
        }
        extractor = LinkExtractor()
        result = extractor.extract_urls(data)
        assert result == []

    def test_rejects_private_ip(self):
        data = {
            "urls": [
                {
                    "url": "http://192.168.1.1/page",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Private",
                },
                {
                    "url": "http://10.0.0.1/page",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Private",
                },
            ]
        }
        extractor = LinkExtractor()
        result = extractor.extract_urls(data)
        assert result == []

    def test_rejects_ftp_scheme(self):
        data = {
            "urls": [
                {
                    "url": "ftp://example.com/file",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "FTP",
                },
            ]
        }
        extractor = LinkExtractor()
        result = extractor.extract_urls(data)
        assert result == []

    def test_keeps_valid_url_among_invalid(self):
        data = {
            "urls": [
                {
                    "url": "not-a-url",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Bad",
                },
                {
                    "url": "https://reuters.com/article/123",
                    "agent": "coverage-center",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Reuters",
                },
            ]
        }
        extractor = LinkExtractor()
        result = extractor.extract_urls(data)
        assert len(result) == 1
        assert result[0].url == "https://reuters.com/article/123"
