"""Deterministic domain-source lookup + fetch task.

Combines :func:`tools.lookup_domain_sources.lookup_domain_sources` and
:class:`swarm_reasoning.agents.web.WebContentExtractor` to produce a list
of candidate sources with fetched content attached. Up to
``MAX_FETCH_ATTEMPTS`` URLs are tried in domain-priority order; the first
one that returns non-empty content is returned. If none succeed, an empty
list is returned (NOT a hallucinated ``SUPPORTS``).

The fetched content is passed to the LLM scorer subagent downstream; this
module does no scoring and makes no alignment judgment.
"""

from __future__ import annotations

import logging

from swarm_reasoning.agents.evidence.tools import lookup_domain_sources as lookup_module
from swarm_reasoning.agents.web import (
    FetchErr,
    FetchOk,
    WebContentExtractor,
)

logger = logging.getLogger(__name__)

MAX_FETCH_ATTEMPTS = 3


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
    query = lookup_module.derive_search_query(
        claim_text,
        persons,
        organizations,
        statistics,
        dates,
    )
    sources = lookup_module.lookup_domain_sources(domain, query)
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
