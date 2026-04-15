"""Shared agent utilities.

Consolidates common helpers used across agent modules and pipeline nodes:
ISO timestamps, exception types, stop-word lists, text scoring, date
normalization, and an async HTTP retry helper.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import Counter
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


# ---------------------------------------------------------------------------
# TF-IDF cosine similarity (ported from claimreview_matcher/scorer.py)
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def _tokenize(text: str) -> list[str]:
    """Lowercase and tokenize, removing stop words."""
    return [w for w in _WORD_RE.findall(text.lower()) if w not in STOP_WORDS]


def cosine_similarity(text_a: str, text_b: str) -> float:
    """Compute TF-IDF-weighted cosine similarity between two texts.

    Uses term frequency vectors (IDF approximated from the two-document corpus).
    Returns a score in [0.0, 1.0].
    """
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    tf_a = Counter(tokens_a)
    tf_b = Counter(tokens_b)

    # Build vocabulary and compute IDF (2-document corpus)
    vocab = set(tf_a) | set(tf_b)
    doc_count = {}
    for term in vocab:
        doc_count[term] = (1 if term in tf_a else 0) + (1 if term in tf_b else 0)

    # TF-IDF vectors
    def tfidf_vector(tf: Counter) -> dict[str, float]:
        total = sum(tf.values())
        vec = {}
        for term in vocab:
            tf_val = tf.get(term, 0) / total if total > 0 else 0
            idf_val = math.log(2 / doc_count[term]) + 1  # smoothed IDF
            vec[term] = tf_val * idf_val
        return vec

    vec_a = tfidf_vector(tf_a)
    vec_b = tfidf_vector(tf_b)

    # Cosine similarity
    dot = sum(vec_a[t] * vec_b[t] for t in vocab)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


# ---------------------------------------------------------------------------
# Date normalization (ported from entity_extractor/publisher.py)
# ---------------------------------------------------------------------------

_DATE_YYYYMMDD = re.compile(r"^\d{8}$")
_DATE_RANGE = re.compile(r"^\d{8}-\d{8}$")
_YEAR_ONLY = re.compile(r"^\d{4}$")


def normalize_date(date_str: str) -> tuple[str, str | None]:
    """Normalize a date string to YYYYMMDD or YYYYMMDD-YYYYMMDD format.

    Returns (normalized_value, note) where note is "date-not-normalized"
    if the string cannot be parsed, None otherwise.
    """
    stripped = date_str.strip()

    if _DATE_YYYYMMDD.match(stripped):
        return stripped, None

    if _DATE_RANGE.match(stripped):
        return stripped, None

    if _YEAR_ONLY.match(stripped):
        return f"{stripped}0101-{stripped}1231", None

    return stripped, "date-not-normalized"
