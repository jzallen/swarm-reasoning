"""Unit tests for evidence tasks.lookup_sources.

Focus: retry behavior and the empty-content signal that triggers the
fallback chain. The actual HTTP extraction is mocked via a stub extractor.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from swarm_reasoning.agents.evidence.tasks.lookup_sources import (
    derive_search_query,
    lookup_domain_sources,
    lookup_sources,
)
from swarm_reasoning.agents.web import FetchErr, FetchOk, WebContentDocument


@dataclass
class _StubExtractor:
    """Minimal extractor stub that returns canned results keyed by URL."""

    by_url: dict

    async def fetch(self, url: str):
        return self.by_url[url]


def _ok(text: str) -> FetchOk:
    doc = WebContentDocument(
        url="https://example",
        text=text,
        accessed_at="2026-04-19T00:00:00Z",
    )
    return FetchOk(document=doc)


def _expected_urls(domain: str, **kwargs) -> list[str]:
    """Compute the URLs lookup_sources will request for a given input."""
    query = derive_search_query(
        kwargs["claim_text"],
        kwargs.get("persons"),
        kwargs.get("organizations"),
        kwargs.get("statistics"),
        kwargs.get("dates"),
    )
    return [s.url for s in lookup_domain_sources(domain, query).sources]


@pytest.mark.asyncio
async def test_lookup_sources_returns_first_successful_fetch():
    """OTHER domain has one source (Google) -- successful fetch returns it."""
    kwargs = dict(
        claim_text="test claim",
        persons=None,
        organizations=None,
        statistics=None,
        dates=None,
    )
    [url] = _expected_urls("OTHER", **kwargs)
    extractor = _StubExtractor(by_url={url: _ok("Real article body about the claim.")})
    result = await lookup_sources(domain="OTHER", extractor=extractor, **kwargs)
    assert len(result) == 1
    assert result[0]["name"] == "Google (.gov/.edu)"
    assert result[0]["url"] == url
    assert "Real article body" in result[0]["content"]


@pytest.mark.asyncio
async def test_lookup_sources_retries_on_empty_content():
    """When the primary source returns empty text, the lookup proceeds to
    the next fallback rather than returning the empty string as evidence."""
    kwargs = dict(
        claim_text="inflation expectations rising",
        persons=None,
        organizations=None,
        statistics=None,
        dates=None,
    )
    urls = _expected_urls("ECONOMICS", **kwargs)
    extractor = _StubExtractor(
        by_url={
            urls[0]: _ok(""),
            urls[1]: _ok("FRED release: monetary policy update ..."),
            urls[2]: FetchErr(reason="not-reached"),
        }
    )
    result = await lookup_sources(domain="ECONOMICS", extractor=extractor, **kwargs)
    assert len(result) == 1
    assert result[0]["url"] == urls[1]
    assert "FRED release" in result[0]["content"]


@pytest.mark.asyncio
async def test_lookup_sources_returns_empty_when_all_attempts_fail():
    """All three ECONOMICS candidates fail -> no fabricated source."""
    kwargs = dict(
        claim_text="q",
        persons=None,
        organizations=None,
        statistics=None,
        dates=None,
    )
    urls = _expected_urls("ECONOMICS", **kwargs)
    extractor = _StubExtractor(
        by_url={
            urls[0]: FetchErr(reason="timeout"),
            urls[1]: FetchErr(reason="404"),
            urls[2]: FetchErr(reason="500"),
        }
    )
    result = await lookup_sources(domain="ECONOMICS", extractor=extractor, **kwargs)
    assert result == []
