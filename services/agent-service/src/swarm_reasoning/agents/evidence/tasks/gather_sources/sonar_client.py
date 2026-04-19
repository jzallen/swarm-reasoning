"""Perplexity Sonar HTTP client (pass-2 of the gather_sources two-pass flow).

Issues a chat-completions request scoped by ``search_domain_filter``
(from pass 1) and an optional date/recency filter, then discards the
synthesis (``choices[].message.content``) and returns the raw
``search_results`` array. The orchestrator parses entries via
:class:`...models.SonarResult`.

Public surface for the gather_sources package:

- :class:`SonarQuery` — DTO bundling the inputs for one Sonar request;
  owns its own cache-key derivation.
- :class:`SonarCache` — sqlite-backed cache of raw ``search_results``.
  Single file, no TTL, no eviction. Managed internally by
  :func:`sonar_search`; calling code never instantiates it.
- :func:`sonar_search` — execute one query, transparently caching by
  default. Pass ``bypass_cache=True`` for a force-fresh call. The
  ``SONAR_CACHE=bypass`` env var disables the cache process-wide
  (production path: set this and no sqlite file is ever created).

Sources:
- https://docs.perplexity.ai/api-reference/chat-completions-post
- https://docs.perplexity.ai/guides/search-domain-filters
- https://docs.perplexity.ai/guides/date-range-filter-guide
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swarm_reasoning.agents.evidence.tasks.gather_sources.models import (
    DiscoveryResult,
    RecencyHint,
)

logger = logging.getLogger(__name__)

SONAR_API_URL = "https://api.perplexity.ai/chat/completions"
SONAR_MODEL = "sonar"
SONAR_MAX_TOKENS = 64  # synthesis is discarded; 64 is a safe floor
SONAR_CONTEXT_SIZE = "low"
_SONAR_TIMEOUT_SECONDS = 15.0
_SONAR_DOMAIN_CAP = 20

_SONAR_CACHE_ENV = "SONAR_CACHE"
_SONAR_CACHE_PATH_ENV = "SONAR_CACHE_PATH"


def _default_cache_path() -> Path:
    """Default sqlite path: ``~/.cache/fact-checker/sonar.db``."""
    return Path.home() / ".cache" / "fact-checker" / "sonar.db"


def _format_sonar_date(iso: str) -> str:
    """Convert ISO8601 ``YYYY-MM-DD`` into Perplexity's ``%m/%d/%Y`` format."""
    y, m, d = iso.split("-")
    return f"{int(m)}/{int(d)}/{int(y)}"


@dataclass(frozen=True)
class SonarQuery:
    """One Sonar request. Owns its cache-key derivation and HTTP body shape.

    Carries everything that distinguishes one Sonar call from another so
    :class:`SonarCache` can stay a generic key->value store and
    :func:`sonar_search` can stay a thin HTTP transport.
    """

    claim_text: str
    domains: tuple[str, ...]
    recency: RecencyHint
    context: str = SONAR_CONTEXT_SIZE
    model: str = SONAR_MODEL

    @classmethod
    def from_discovery(
        cls,
        discovery: DiscoveryResult,
        *,
        claim_text: str,
        allowed_domains: tuple[str, ...],
    ) -> "SonarQuery":
        """Build a query from a discovery result and post-filter allowlist.

        ``allowed_domains`` is the post-denylist subset of
        ``discovery.domains`` and may be tighter than the discovery's
        own domain list.
        """
        return cls(
            claim_text=claim_text,
            domains=allowed_domains,
            recency=discovery.recency,
        )

    @property
    def cache_key(self) -> str:
        """sha256 over the request shape; ``claim_text`` is normalized first."""
        normalized = self.claim_text.strip().lower()
        payload = json.dumps(
            [
                self.model,
                sorted(self.domains),
                self.recency.window,
                self.recency.after_date,
                self.recency.before_date,
                self.context,
                normalized,
            ],
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_request_body(self, *, max_tokens: int = SONAR_MAX_TOKENS) -> dict[str, Any]:
        """Project to the Perplexity chat-completions request body shape."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": f"Find authoritative sources for this claim: {self.claim_text}",
                }
            ],
            "search_domain_filter": list(self.domains)[:_SONAR_DOMAIN_CAP],
            "web_search_options": {"search_context_size": self.context},
            "max_tokens": max_tokens,
        }
        if self.recency.window:
            body["search_recency_filter"] = self.recency.window
        if self.recency.after_date:
            body["search_after_date_filter"] = _format_sonar_date(self.recency.after_date)
        if self.recency.before_date:
            body["search_before_date_filter"] = _format_sonar_date(self.recency.before_date)
        return body


class SonarCache:
    """sqlite-backed cache of Sonar ``search_results`` arrays.

    Single file, no TTL, no eviction (``rm`` to clear). Concurrent-safe
    at the sqlite level (one connection per call). Constructed lazily by
    :func:`sonar_search` on first non-bypassed call; calling code never
    instantiates this directly.

    Bypass: setting ``SONAR_CACHE=bypass`` in the environment prevents
    construction and skips both ``get`` and ``set``.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path(os.environ.get(_SONAR_CACHE_PATH_ENV) or _default_cache_path())
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sonar_results "
                "(key TEXT PRIMARY KEY, results TEXT NOT NULL)"
            )

    @staticmethod
    def bypass() -> bool:
        """Return True iff ``SONAR_CACHE=bypass`` is set in the environment."""
        return os.environ.get(_SONAR_CACHE_ENV, "").lower() == "bypass"

    def get(self, key: str) -> list[dict] | None:
        """Look up cached search_results for ``key``; return None on miss."""
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                "SELECT results FROM sonar_results WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, key: str, results: list[dict]) -> None:
        """Insert or replace cached search_results for ``key``."""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sonar_results (key, results) VALUES (?, ?)",
                (key, json.dumps(results)),
            )


_cache_singleton: SonarCache | None = None


def _get_cache() -> SonarCache:
    """Lazily construct the process-wide :class:`SonarCache`."""
    global _cache_singleton
    if _cache_singleton is None:
        _cache_singleton = SonarCache()
    return _cache_singleton


async def sonar_search(
    query: SonarQuery,
    *,
    bypass_cache: bool = False,
) -> list[dict]:
    """Execute *query* against Perplexity Sonar, transparently caching.

    Cache contract: by default a cache hit short-circuits the HTTP call
    and a miss writes back after a successful call. Pass
    ``bypass_cache=True`` for a force-fresh call. The ``SONAR_CACHE=bypass``
    env var disables the cache process-wide and prevents the sqlite file
    from being created at all.

    Returns the raw ``search_results`` array. Returns ``[]`` when
    ``PERPLEXITY_API_KEY`` is unset or the upstream response is non-2xx.
    """
    import httpx

    cache_active = not bypass_cache and not SonarCache.bypass()
    if cache_active:
        cached = _get_cache().get(query.cache_key)
        if cached is not None:
            return cached

    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        logger.warning("PERPLEXITY_API_KEY not configured")
        return []

    async with httpx.AsyncClient(timeout=_SONAR_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            SONAR_API_URL,
            json=query.to_request_body(),
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code >= 400:
        logger.warning("Sonar HTTP %s: %s", resp.status_code, resp.text[:200])
        return []

    results = resp.json().get("search_results", [])
    if cache_active:
        _get_cache().set(query.cache_key, results)
    return results
