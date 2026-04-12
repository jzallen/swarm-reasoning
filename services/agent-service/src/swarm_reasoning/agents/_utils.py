"""Shared agent utilities.

Consolidates common helpers that were duplicated across multiple agent
modules: ISO timestamps, exception types, stop-word lists, an async HTTP
retry helper, and a lightweight handler-singleton registry.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, TypeVar

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------


class StreamNotFoundError(Exception):
    """Raised when required upstream observations are not found."""


# ---------------------------------------------------------------------------
# Stop words (superset of coverage_core + domain_evidence lists)
# ---------------------------------------------------------------------------

STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "and",
        "but",
        "or",
        "not",
        "so",
        "yet",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "he",
        "she",
        "they",
        "them",
    }
)


# ---------------------------------------------------------------------------
# Async HTTP retry helper
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 10.0
_DEFAULT_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_DEFAULT_MAX_RETRIES = 1
_DEFAULT_BACKOFF = 1.0


async def resilient_get(
    url: str,
    *,
    params: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    retry_statuses: frozenset[int] = _DEFAULT_RETRY_STATUSES,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    backoff: float = _DEFAULT_BACKOFF,
    follow_redirects: bool = False,
    max_redirects: int = 5,
) -> httpx.Response:
    """GET *url* with automatic retry on transient HTTP errors.

    Parameters
    ----------
    url:
        The URL to fetch.
    params:
        Optional query-string parameters.
    timeout:
        Per-request timeout in seconds (default 10).
    retry_statuses:
        HTTP status codes that trigger a retry (default 429 + 5xx).
    max_retries:
        Number of retries after the initial attempt (default 1).
    backoff:
        Seconds to sleep between retries (default 1).
    follow_redirects:
        Whether to follow HTTP redirects (default False).
    max_redirects:
        Maximum number of redirects when *follow_redirects* is True.

    Returns
    -------
    httpx.Response
        The final response (may still be an error status if retries are
        exhausted).
    """
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
    ) as client:
        resp = await client.get(url, params=params)
        attempts = 0
        while resp.status_code in retry_statuses and attempts < max_retries:
            attempts += 1
            logger.debug(
                "resilient_get retry %d/%d for %s (HTTP %d)",
                attempts,
                max_retries,
                url,
                resp.status_code,
            )
            await asyncio.sleep(backoff)
            resp = await client.get(url, params=params)
        return resp


# ---------------------------------------------------------------------------
# Handler singleton registry
# ---------------------------------------------------------------------------

T = TypeVar("T")

_REGISTRY: dict[str, Any] = {}


def register_handler(name: str):
    """Class decorator that registers a handler class under *name*.

    The handler instance is lazily created on the first ``get_handler(name)``
    call (matching the existing singleton pattern used across all agents).

    Usage::

        @register_handler("domain-evidence")
        class DomainEvidenceHandler:
            ...

        handler = get_handler("domain-evidence")
    """

    def decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = {"cls": cls, "instance": None}
        return cls

    return decorator


def get_handler(name: str) -> Any:
    """Return the singleton instance for the handler registered under *name*.

    Raises ``KeyError`` if *name* was never registered.
    """
    entry = _REGISTRY[name]
    if entry["instance"] is None:
        entry["instance"] = entry["cls"]()
    return entry["instance"]


def reset_handlers() -> None:
    """Reset all cached handler instances (useful in tests)."""
    for entry in _REGISTRY.values():
        entry["instance"] = None
