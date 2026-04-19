"""Two-pass authoritative-source gathering for the evidence agent.

Pass 1: a Haiku source-discovery subagent (built in :mod:`...agent`) reads
the claim, its domain classification, and its entities and returns up to
20 authoritative source domains plus an optional recency hint. The
domains are post-filtered against a hand-curated denylist
(``denylist.json``) of low-quality sources.

Pass 2: Perplexity Sonar is queried with the surviving allow-list and
the recency hint, and we keep only the raw ``search_results`` array
(synthesis is discarded). Up to ``_MAX_FETCH_ATTEMPTS`` candidates are
fetched in order via :class:`WebContentExtractor`; the first non-empty
fetch is returned in the standard ``[{name, url, content}]`` shape.

There is intentionally NO route-table fallback: every failure surface
(discovery exception, empty-after-denylist, Sonar exception, zero
candidates / all-fetches-failed) returns ``[]`` so the downstream LLM
scorer can emit ABSENT honestly. Operators can distinguish the four
exit sites by the ``share_progress`` line emitted at each one.

The optional ``sonar_cache`` parameter is for local-dev iteration only;
the agent-service never instantiates :class:`SonarCache`. Production
passes ``None`` and Sonar is called on every invocation. ``SONAR_CACHE``
env var ``bypass`` short-circuits the cache even when an instance is
provided.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from swarm_reasoning.agents.evidence.tasks.gather_sources.agent import DISCOVERY_NAME
from swarm_reasoning.agents.evidence.tasks.gather_sources.cache import (
    SonarCache,
    _cache_key,
)
from swarm_reasoning.agents.evidence.tasks.gather_sources.models import (
    DiscoveryResult,
    SonarResult,
)
from swarm_reasoning.agents.evidence.tasks.gather_sources.sonar_client import (
    SONAR_CONTEXT_SIZE,
    SONAR_MODEL,
    _sonar_search,
)
from swarm_reasoning.agents.messaging import share_progress
from swarm_reasoning.agents.web import FetchErr, FetchOk, WebContentExtractor

logger = logging.getLogger(__name__)

_MAX_FETCH_ATTEMPTS = 3  # Sonar candidates to try before giving up

_denylist_cache: frozenset[str] | None = None
_routes_cache: dict[str, list[dict]] | None = None


def _load_denylist() -> frozenset[str]:
    """Load and cache the low-quality-domain denylist from ``denylist.json``."""
    global _denylist_cache
    if _denylist_cache is None:
        with open(Path(__file__).with_name("denylist.json")) as f:
            _denylist_cache = frozenset(d.lower() for d in json.load(f))
    return _denylist_cache


def _filter_denylist(domains: tuple[str, ...]) -> tuple[str, ...]:
    """Drop any domain present in the denylist (case-insensitive)."""
    deny = _load_denylist()
    return tuple(d for d in domains if d.lower() not in deny)


def _load_routes() -> dict[str, list[dict]]:
    """Load and cache the per-domain seed routing table from ``routes.json``."""
    global _routes_cache
    if _routes_cache is None:
        with open(Path(__file__).with_name("routes.json")) as f:
            _routes_cache = json.load(f)
    return _routes_cache


def _seed_domains_for(domain: str) -> list[str]:
    """Return curated bare hostnames for the pass-1 ``<seeds>`` prompt section.

    Assumes ``routes.json`` is well-formed: it is hand-curated and
    version-controlled, so a malformed entry would be a deploy-time
    config error -- surfaced loudly on the first CLI smoke test.
    """
    routes = _load_routes()
    entries = routes.get(domain.upper(), routes.get("OTHER", []))
    hosts: list[str] = []
    for entry in entries:
        host = (urlparse(entry["url_template"].format(query="x")).hostname or "").removeprefix(
            "www."
        )
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _format_discovery_prompt(
    claim_text: str,
    domain: str,
    persons: list[str] | None,
    organizations: list[str] | None,
    dates: list[str] | None,
    statistics: list[str] | None,
    seeds: list[str],
) -> str:
    """Build the user message for the discovery subagent (pass 1)."""
    seeds_block = " ".join(seeds) if seeds else ""
    return (
        f"Claim: {claim_text}\n"
        f"Domain: {domain}\n"
        f"Persons: {', '.join(persons or []) or '(none)'}\n"
        f"Organizations: {', '.join(organizations or []) or '(none)'}\n"
        f"Dates: {', '.join(dates or []) or '(none)'}\n"
        f"Statistics: {', '.join(statistics or []) or '(none)'}\n\n"
        f"<seeds>{seeds_block}</seeds>\n\n"
        "List up to 20 authoritative domains and call "
        "record_authoritative_domains exactly once."
    )


async def gather_sources(
    *,
    claim_text: str,
    domain: str,
    persons: list[str] | None,
    organizations: list[str] | None,
    statistics: list[str] | None,
    dates: list[str] | None,
    extractor: WebContentExtractor,
    subagent: Any,
    sonar_cache: SonarCache | None = None,
) -> list[dict]:
    """Run the two-pass discovery → Sonar → fetch flow.

    Returns ``[{name, url, content}]`` for the first non-empty fetched
    candidate, or ``[]`` at any of four honest-empty exit sites.
    """
    from langchain_core.messages import HumanMessage

    seeds = _seed_domains_for(domain)
    prompt = _format_discovery_prompt(
        claim_text, domain, persons, organizations, dates, statistics, seeds
    )
    config = {
        "configurable": {
            "thread_id": f"{DISCOVERY_NAME}-{uuid.uuid4()}",
            "checkpoint_ns": "",
        }
    }

    try:
        raw = await subagent.ainvoke({"messages": [HumanMessage(content=prompt)]}, config=config)
    except Exception as exc:  # pragma: no cover -- defensive (broad: network boundary)
        logger.warning("discovery subagent raised %s: %s", type(exc).__name__, exc)
        share_progress("Source discovery failed; no domain evidence.")
        return []

    discovery = DiscoveryResult.from_state(raw)
    allow = _filter_denylist(discovery.domains)
    if not allow:
        share_progress("Source discovery returned no allowed domains; no domain evidence.")
        return []

    key = _cache_key(
        claim_text=claim_text,
        domains=allow,
        recency=discovery.recency,
        context=SONAR_CONTEXT_SIZE,
        model=SONAR_MODEL,
    )
    cached = sonar_cache.get(key) if (sonar_cache and not SonarCache.bypass()) else None
    if cached is not None:
        raw_results = cached
    else:
        try:
            raw_results = await _sonar_search(
                claim_text=claim_text,
                domains=list(allow),
                recency=discovery.recency,
            )
        except Exception as exc:  # pragma: no cover -- network boundary, broad on purpose
            logger.warning("sonar_search raised %s: %s", type(exc).__name__, exc)
            share_progress("Sonar search failed; no domain evidence.")
            return []
        if sonar_cache and not SonarCache.bypass():
            sonar_cache.set(key, raw_results)

    candidates = [SonarResult.from_result(r) for r in raw_results[:_MAX_FETCH_ATTEMPTS]]
    if not candidates:
        share_progress("Sonar returned zero candidates; no domain evidence.")
        return []

    for c in candidates:
        result = await extractor.fetch(c.url)
        match result:
            case FetchOk(document=doc) if doc.text:
                return [
                    {
                        "name": c.title or c.url,
                        "url": c.url,
                        "content": doc.text,
                    }
                ]
            case FetchOk():
                logger.info("fetch for %s returned empty content", c.url)
                continue
            case FetchErr(reason=code):
                logger.info("fetch failed for %s: %s", c.url, code)
                continue

    share_progress("All Sonar candidates failed to fetch; no domain evidence.")
    return []
