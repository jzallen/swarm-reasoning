"""Evidence-gathering @tool definitions for LangChain agents (ADR-004).

Provides search_factchecks as a @tool-decorated function that wraps Google Fact
Check Tools API query building, HTTP call, TF-IDF match scoring, and
CLAIMREVIEW_* observation publishing. AgentContext is injected at runtime via
InjectedToolArg.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Annotated

import httpx
from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.claimreview_matcher.scorer import cosine_similarity
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType

logger = logging.getLogger(__name__)

API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
MATCH_THRESHOLD = 0.50


def _first_review(result: dict) -> dict:
    """Return the first ClaimReview entry from a Fact Check API result, or ``{}``."""
    return result.get("claimReview", [{}])[0]


def _build_query(claim: str, persons: list[str], organizations: list[str]) -> str:
    """Build API query from normalized claim and top entities."""
    parts = []
    for name in (persons + organizations)[:2]:
        parts.append(name)
    parts.append(claim)
    query = " ".join(parts)
    return query[:100]  # API query limit


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


async def _publish_match(context: AgentContext, match: dict, score: float) -> None:
    """Publish 5 observations for a successful match."""
    review = _first_review(match)
    rating = review.get("textualRating", "Unknown")
    publisher = review.get("publisher", {}).get("name", "Unknown")
    url = review.get("url", "")
    system = publisher.upper().replace(" ", "_")

    await context.publish_obs(
        code=ObservationCode.CLAIMREVIEW_MATCH,
        value="TRUE^Match Found^FCK",
        value_type=ValueType.CWE,
        method="lookup_claimreview",
    )

    await context.publish_obs(
        code=ObservationCode.CLAIMREVIEW_VERDICT,
        value=f"{rating.upper().replace(' ', '_')}^{rating}^{system}",
        value_type=ValueType.CWE,
        method="lookup_claimreview",
    )

    await context.publish_obs(
        code=ObservationCode.CLAIMREVIEW_SOURCE,
        value=publisher,
        value_type=ValueType.ST,
        method="lookup_claimreview",
    )

    await context.publish_obs(
        code=ObservationCode.CLAIMREVIEW_URL,
        value=url or "N/A",
        value_type=ValueType.ST,
        method="lookup_claimreview",
    )

    await context.publish_obs(
        code=ObservationCode.CLAIMREVIEW_MATCH_SCORE,
        value=f"{score:.2f}",
        value_type=ValueType.NM,
        method="compute_similarity",
        units="score",
        reference_range="0.0-1.0",
    )


async def _publish_negative(
    context: AgentContext, status: str = "F", note: str | None = None
) -> None:
    """Publish 2 observations for no-match or error outcomes."""
    await context.publish_obs(
        code=ObservationCode.CLAIMREVIEW_MATCH,
        value="FALSE^No Match^FCK",
        value_type=ValueType.CWE,
        status=status,
        method="lookup_claimreview",
        note=note,
    )
    await context.publish_obs(
        code=ObservationCode.CLAIMREVIEW_MATCH_SCORE,
        value="0.0",
        value_type=ValueType.NM,
        status=status,
        method="compute_similarity",
        units="score",
        reference_range="0.0-1.0",
    )


@tool
async def search_factchecks(
    claim: str,
    persons: Annotated[list[str], "Named persons relevant to the claim"] = None,
    organizations: Annotated[list[str], "Named organizations relevant to the claim"] = None,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Search fact-check databases for existing reviews of a claim.

    Queries the Google Fact Check Tools API with the normalized claim and
    entity names, scores results via TF-IDF cosine similarity, and publishes
    CLAIMREVIEW_* observations. Publishes 5 observations on match (MATCH,
    VERDICT, SOURCE, URL, MATCH_SCORE) or 2 on no-match/error (MATCH,
    MATCH_SCORE).

    Args:
        claim: The normalized claim text to search for.
        persons: Named persons relevant to the claim (improves search precision).
        organizations: Named organizations relevant to the claim.
        context: Injected AgentContext -- not exposed to the LLM.

    Returns:
        Summary of the search result (match found with source, or no match).
    """
    persons = persons or []
    organizations = organizations or []

    api_key = os.environ.get("GOOGLE_FACTCHECK_API_KEY", "")
    if not api_key:
        logger.warning("GOOGLE_FACTCHECK_API_KEY not configured")
        await _publish_negative(context, status="X", note="API key not configured")
        return "Error: GOOGLE_FACTCHECK_API_KEY not configured"

    query = _build_query(claim, persons, organizations)

    try:
        results = await _call_api(query, api_key)
    except Exception as exc:
        logger.warning("ClaimReview API error: %s", exc)
        await _publish_negative(context, status="X", note=f"API error: {exc}")
        return f"Error: API call failed -- {exc}"

    if not results:
        await _publish_negative(context)
        return "No matching fact-checks found"

    best_match, best_score = _score_matches(results, claim)

    if best_score < MATCH_THRESHOLD:
        await _publish_negative(context)
        return "No matching fact-checks found (below similarity threshold)"

    await _publish_match(context, best_match, best_score)

    review = _first_review(best_match)
    source_name = review.get("publisher", {}).get("name", "Unknown")
    rating = review.get("textualRating", "Unknown")
    return f"Match found: {rating} (from {source_name}, score={best_score:.2f})"
