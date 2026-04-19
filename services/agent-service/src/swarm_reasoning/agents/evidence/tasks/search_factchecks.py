"""Deterministic ClaimReview search task (no LLM, no state).

Queries the Google Fact Check Tools API, scores results via TF-IDF
cosine similarity, and returns a ``list[dict]`` suitable for the
evidence entrypoint's ``claimreview_matches`` output. Each entry's
``url`` is the real review page from the API response, never a
synthesized search query.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from swarm_reasoning.agents._utils import cosine_similarity

logger = logging.getLogger(__name__)

API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
MATCH_THRESHOLD = 0.50


def _empty_list_on_error(func):
    """Async decorator: log warning and return ``[]`` on any exception."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            logger.warning("%s failed: %s", func.__name__, exc)
            return []

    return wrapper


@dataclass(frozen=True)
class ReviewedClaim:
    """A scored ClaimReview candidate. Built via :meth:`from_result`."""

    review: dict
    claim: str
    score: float

    @classmethod
    def from_result(cls, result: dict, normalized_claim: str) -> ReviewedClaim:
        review = result.get("claimReview", [{}])[0]
        claim = review.get("title", result.get("text", ""))
        return cls(
            review=review,
            claim=claim,
            score=cosine_similarity(normalized_claim, claim),
        )

    def serialize(
        self,
        skip_if: Callable[[ReviewedClaim], bool] | None = None,
    ) -> list[dict]:
        """Return the output entry, or ``[]`` if *skip_if* is true for this claim."""
        if skip_if is not None and skip_if(self):
            return []
        return [
            {
                "source": self.review.get("publisher", {}).get("name", "Unknown"),
                "rating": self.review.get("textualRating", "Unknown"),
                "url": self.review.get("url", ""),
                "score": round(self.score, 2),
            }
        ]


class EmptyReviewedClaim(ReviewedClaim):
    """Null object: returned when the API yields no results."""

    def __init__(self) -> None:
        super().__init__(review={}, claim="", score=0.0)

    def serialize(
        self,
        skip_if: Callable[[ReviewedClaim], bool] | None = None,
    ) -> list[dict]:
        return []


@_empty_list_on_error
async def _query_google_factcheck(
    claim: str,
    persons: list[str],
    organizations: list[str],
    api_key: str,
) -> list[dict]:
    """Query Google Fact Check Tools API. Retries once on 429. Always returns a list."""

    def _build_query() -> str:
        parts: list[str] = list((persons + organizations)[:2])
        parts.append(claim)
        return " ".join(parts)[:100]

    query = _build_query()

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(API_URL, params={"query": query, "key": api_key})

        if resp.status_code == 429:
            await asyncio.sleep(2)
            resp = await client.get(API_URL, params={"query": query, "key": api_key})

        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code}",
                request=resp.request,
                response=resp,
            )

        return resp.json().get("claims", [])


def _score_matches(results: list[dict], normalized_claim: str) -> ReviewedClaim:
    """Return the highest-scoring :class:`ReviewedClaim`, or :class:`EmptyReviewedClaim`."""
    if not results:
        return EmptyReviewedClaim()
    return functools.reduce(
        lambda best, candidate: candidate if candidate.score > best.score else best,
        (ReviewedClaim.from_result(r, normalized_claim) for r in results),
    )


async def search_factcheck_matches(
    claim_text: str,
    persons: list[str] | None = None,
    organizations: list[str] | None = None,
) -> list[dict]:
    """Return structured ClaimReview matches for *claim_text*, or ``[]``.

    The API response's ``url`` field is preserved verbatim (e.g.
    politifact.com/factchecks/...).
    """
    persons = persons or []
    organizations = organizations or []

    api_key = os.environ.get("GOOGLE_FACTCHECK_API_KEY", "")
    if not api_key:
        logger.warning("GOOGLE_FACTCHECK_API_KEY not configured")
        return []

    return _score_matches(
        await _query_google_factcheck(claim_text, persons, organizations, api_key),
        claim_text,
    ).serialize(skip_if=lambda c: c.score < MATCH_THRESHOLD)
