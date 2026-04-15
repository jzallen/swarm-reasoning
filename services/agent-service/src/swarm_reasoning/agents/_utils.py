"""Shared agent utilities.

Consolidates common helpers used across agent modules and pipeline nodes:
ISO timestamps, exception types, stop-word lists, and an async HTTP retry
helper.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

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
# Stop words — single canonical set used by all agents
# ---------------------------------------------------------------------------

STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "about",
        "above",
        "after",
        "all",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "during",
        "each",
        "either",
        "every",
        "few",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "how",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "may",
        "might",
        "more",
        "most",
        "my",
        "neither",
        "no",
        "nor",
        "not",
        "of",
        "on",
        "only",
        "or",
        "other",
        "our",
        "out",
        "own",
        "same",
        "shall",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "up",
        "very",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "will",
        "with",
        "would",
        "yet",
        "you",
        "your",
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
