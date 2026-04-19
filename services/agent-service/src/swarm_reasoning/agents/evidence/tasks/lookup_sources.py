"""Deterministic domain-source lookup + fetch task.

Loads a domain routing table (``routes.json``) mapping claim domains to
authoritative sources, derives a search query from claim context,
formats the candidate URLs, and fetches the first non-empty result via
:class:`swarm_reasoning.agents.web.WebContentExtractor`.

Returns a list of ``{name, url, content}`` dicts -- at most one entry
in practice (the first successful fetch) -- or ``[]`` if every
candidate URL failed or returned empty content. The fetched content is
passed to the LLM scorer subagent downstream; this module does no
scoring and makes no alignment judgment.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from swarm_reasoning.agents._utils import STOP_WORDS
from swarm_reasoning.agents.web import (
    FetchErr,
    FetchOk,
    WebContentExtractor,
)

logger = logging.getLogger(__name__)

MAX_FETCH_ATTEMPTS = 3

_routes_cache: dict[str, list[dict]] | None = None


def _load_routes() -> dict[str, list[dict]]:
    """Load and cache the domain routing table from ``evidence/routes.json``."""
    global _routes_cache
    if _routes_cache is None:
        routes_path = Path(__file__).parent.parent / "routes.json"
        with open(routes_path) as f:
            _routes_cache = json.load(f)
    return _routes_cache


@dataclass
class DomainSource:
    """A single authoritative source for a claim domain (formatted, query-bound)."""

    name: str
    url: str


@dataclass
class DomainSources:
    """Ordered collection of authoritative sources for a claim domain.

    Entries are query-bound: each ``url`` already has the search query
    interpolated.
    """

    sources: list[DomainSource]


def format_source_url(url_template: str, query: str) -> str:
    """Format a source URL template with a URL-encoded search query."""
    return url_template.format(query=quote_plus(query))


def lookup_domain_sources(domain: str, query: str) -> DomainSources:
    """Look up authoritative sources for a claim domain, bound to a search query.

    Args:
        domain: Domain category (HEALTHCARE, ECONOMICS, POLICY, SCIENCE,
                ELECTION, CRIME, OTHER). Case-insensitive.
        query:  Search query interpolated into each source URL template.

    Returns:
        :class:`DomainSources` in priority order with each URL pre-formatted.
    """
    routes = _load_routes()
    key = domain.upper()
    raw_sources = routes.get(key, routes.get("OTHER", []))
    return DomainSources(
        sources=[
            DomainSource(name=s["name"], url=format_source_url(s["url_template"], query))
            for s in raw_sources
        ]
    )


def derive_search_query(
    normalized_claim: str,
    persons: list[str] | None = None,
    organizations: list[str] | None = None,
    statistics: list[str] | None = None,
    dates: list[str] | None = None,
) -> str:
    """Derive an optimized search query from claim context.

    Combines top entity names, claim keywords (minus stop words),
    statistics, and dates into a search string truncated to 80 chars.
    """
    persons = persons or []
    organizations = organizations or []
    statistics = statistics or []
    dates = dates or []

    parts: list[str] = []

    for name in (persons + organizations)[:3]:
        parts.append(name)

    words = normalized_claim.lower().split()
    parts.extend(w for w in words if w not in STOP_WORDS)

    for stat in statistics[:2]:
        parts.append(stat)

    for date in dates[:1]:
        parts.append(date)

    query = " ".join(parts)

    if len(query) <= 80:
        return query

    truncated = query[:80]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space]
    return truncated


async def lookup_sources(
    *,
    claim_text: str,
    domain: str,
    persons: list[str] | None,
    organizations: list[str] | None,
    statistics: list[str] | None,
    dates: list[str] | None,
    extractor: WebContentExtractor,
) -> list[dict]:
    """Resolve and fetch domain-authoritative sources for a claim.

    Returns a list of ``{"name", "url", "content"}`` dicts -- at most one
    entry in practice (the first successful fetch) -- or ``[]`` if every
    candidate URL failed or returned empty content.

    Callers MUST NOT treat a non-empty result as evidence in favor of the
    claim: the content may be an empty search-result page, a login wall,
    or an unrelated article. The LLM scorer decides alignment.
    """
    query = derive_search_query(
        claim_text,
        persons,
        organizations,
        statistics,
        dates,
    )
    sources = lookup_domain_sources(domain, query)
    candidates = sources.sources[:MAX_FETCH_ATTEMPTS]

    for candidate in candidates:
        result = await extractor.fetch(candidate.url)
        match result:
            case FetchOk(document=doc) if doc.text:
                return [
                    {
                        "name": candidate.name,
                        "url": candidate.url,
                        "content": doc.text,
                    }
                ]
            case FetchOk():
                logger.info("fetch for %s returned empty content", candidate.url)
                continue
            case FetchErr(reason=code):
                logger.info("fetch failed for %s: %s", candidate.url, code)
                continue
    return []
