"""ClaimReview API search via Google Fact Check Tools (ADR-004).

Queries the Google Fact Check Tools API, scores results via TF-IDF cosine
similarity, and returns structured match data.  No observation publishing --
that is the pipeline node's responsibility.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

import httpx

from swarm_reasoning.agents._utils import cosine_similarity

logger = logging.getLogger(__name__)

API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
MATCH_THRESHOLD = 0.50


@dataclass
class FactCheckResult:
    """Structured result from a ClaimReview API search."""

    matched: bool
    rating: str
    source: str
    url: str
    score: float
    error: str | None = None


def _first_review(result: dict) -> dict:
    """Return the first ClaimReview entry from a Fact Check API result, or ``{}``."""
    return result.get("claimReview", [{}])[0]


def _build_query(claim: str, persons: list[str], organizations: list[str]) -> str:
    """Build API query from normalized claim and top entities."""
    parts: list[str] = []
    for name in (persons + organizations)[:2]:
        parts.append(name)
    parts.append(claim)
    query = " ".join(parts)
    return query[:100]


async def _call_api(query: str, api_key: str) -> list[dict]:
    """Query Google Fact Check Tools API. Retries once on 429."""
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

        data = resp.json()
        return data.get("claims", [])


def _score_matches(results: list[dict], normalized_claim: str) -> tuple[dict, float]:
    """Score ClaimReview results via TF-IDF cosine similarity."""
    best_match = results[0]
    best_score = 0.0

    for result in results:
        claim_reviewed = _first_review(result).get("title", result.get("text", ""))
        score = cosine_similarity(normalized_claim, claim_reviewed)
        if score > best_score:
            best_score = score
            best_match = result

    return best_match, best_score


async def search_factchecks(
    claim: str,
    persons: list[str] | None = None,
    organizations: list[str] | None = None,
) -> FactCheckResult:
    """Search fact-check databases for existing reviews of a claim.

    Queries the Google Fact Check Tools API with the normalized claim and
    entity names, scores results via TF-IDF cosine similarity, and returns
    a structured result.

    Args:
        claim: The normalized claim text to search for.
        persons: Named persons relevant to the claim.
        organizations: Named organizations relevant to the claim.

    Returns:
        FactCheckResult with match status, rating, source, URL, and score.
    """
    persons = persons or []
    organizations = organizations or []

    api_key = os.environ.get("GOOGLE_FACTCHECK_API_KEY", "")
    if not api_key:
        logger.warning("GOOGLE_FACTCHECK_API_KEY not configured")
        return FactCheckResult(
            matched=False,
            rating="",
            source="",
            url="",
            score=0.0,
            error="GOOGLE_FACTCHECK_API_KEY not configured",
        )

    query = _build_query(claim, persons, organizations)

    try:
        results = await _call_api(query, api_key)
    except Exception as exc:
        logger.warning("ClaimReview API error: %s", exc)
        return FactCheckResult(
            matched=False,
            rating="",
            source="",
            url="",
            score=0.0,
            error=f"API call failed: {exc}",
        )

    if not results:
        return FactCheckResult(matched=False, rating="", source="", url="", score=0.0)

    best_match, best_score = _score_matches(results, claim)

    if best_score < MATCH_THRESHOLD:
        return FactCheckResult(matched=False, rating="", source="", url="", score=best_score)

    review = _first_review(best_match)
    return FactCheckResult(
        matched=True,
        rating=review.get("textualRating", "Unknown"),
        source=review.get("publisher", {}).get("name", "Unknown"),
        url=review.get("url", ""),
        score=best_score,
    )
