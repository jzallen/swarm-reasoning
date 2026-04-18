"""Domain-authoritative source lookup and query derivation (ADR-004).

Loads a domain routing table (routes.json) mapping claim domains to
authoritative sources, and provides helpers to derive search queries
and format source URLs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from swarm_reasoning.agents._utils import STOP_WORDS

# Lazy-loaded routes cache
_routes_cache: dict[str, list[dict]] | None = None


def _load_routes() -> dict[str, list[dict]]:
    """Load and cache the domain routing table."""
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
    interpolated. Use :meth:`to_json` to serialize for tool output.
    """

    sources: list[DomainSource]

    def to_json(self) -> str:
        """Serialize the collection as a JSON array of ``{name, url}`` objects."""
        return json.dumps([{"name": s.name, "url": s.url} for s in self.sources])


def lookup_domain_sources(domain: str, query: str) -> DomainSources:
    """Look up authoritative sources for a claim domain, bound to a search query.

    Args:
        domain: The domain category (e.g. HEALTHCARE, ECONOMICS, POLICY,
                SCIENCE, ELECTION, CRIME, OTHER). Case-insensitive.
        query:  The search query to interpolate into each source URL template.

    Returns:
        A :class:`DomainSources` collection in priority order (prefer
        earlier entries), with each URL already query-formatted.
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

    Combines entity names, claim keywords (minus stop words), statistics,
    and dates into a search string truncated to 80 characters.

    Args:
        normalized_claim: The normalized claim text.
        persons: Person entity names.
        organizations: Organization entity names.
        statistics: Numeric statistics from the claim.
        dates: Date references from the claim.

    Returns:
        An optimized search query string (max 80 characters).
    """
    persons = persons or []
    organizations = organizations or []
    statistics = statistics or []
    dates = dates or []

    parts: list[str] = []

    # Prepend prominent entity names
    for name in (persons + organizations)[:3]:
        parts.append(name)

    # Add claim text minus stop words
    words = normalized_claim.lower().split()
    filtered = [w for w in words if w not in STOP_WORDS]
    parts.extend(filtered)

    # Append statistics verbatim
    for stat in statistics[:2]:
        parts.append(stat)

    # Append dates
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


def format_source_url(url_template: str, query: str) -> str:
    """Format a source URL template with a search query.

    Args:
        url_template: URL template containing a ``{query}`` placeholder.
        query: The search query to insert (will be URL-encoded).

    Returns:
        The formatted URL ready for fetching.
    """
    return url_template.format(query=quote_plus(query))
