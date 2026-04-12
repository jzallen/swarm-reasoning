"""ClaimReview matcher handler -- Google Fact Check Tools API integration.

Queries the Google Fact Check Tools API with the normalized claim and entity
names, scores matches via TF-IDF cosine similarity, and publishes 5 observations
on match or 2 on no-match.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
import redis.asyncio as aioredis

from swarm_reasoning.agents.claimreview_matcher.scorer import cosine_similarity
from swarm_reasoning.agents.fanout_base import ClaimContext, FanoutBase
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "claimreview-matcher"
API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

MATCH_THRESHOLD = 0.50


def _first_review(result: dict) -> dict:
    """Return the first ClaimReview entry from a Fact Check API result, or ``{}``."""
    return result.get("claimReview", [{}])[0]


def _build_query(context: ClaimContext) -> str:
    """Build API query from normalized claim and top entities."""
    parts = []
    # Add most prominent entity names for precision
    for name in (context.persons + context.organizations)[:2]:
        parts.append(name)
    parts.append(context.normalized_claim)
    query = " ".join(parts)
    return query[:100]  # API query limit


class ClaimReviewMatcherHandler(FanoutBase):
    """Queries Google Fact Check Tools API and scores matches."""

    AGENT_NAME = AGENT_NAME

    def __init__(self, redis_config: RedisConfig | None = None) -> None:
        super().__init__(redis_config)
        self._api_key = os.environ.get("GOOGLE_FACTCHECK_API_KEY", "")

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.CLAIMREVIEW_MATCH

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        # Check API key
        if not self._api_key:
            logger.warning("GOOGLE_FACTCHECK_API_KEY not configured")
            await self._publish_negative(stream, sk, run_id, status="X", note="API key not configured")
            return

        query = _build_query(context)
        await self._publish_progress(redis_client, run_id, "Searching fact-check databases...")

        # Call API
        try:
            results = await self._call_api(query)
        except Exception as exc:
            logger.warning("ClaimReview API error: %s", exc)
            await self._publish_negative(stream, sk, run_id, status="X", note=f"API error: {exc}")
            return

        if not results:
            await self._publish_negative(stream, sk, run_id)
            await self._publish_progress(redis_client, run_id, "No matching fact-checks found")
            return

        # Score matches
        best_match, best_score = self._score_matches(results, context.normalized_claim)

        if best_score < MATCH_THRESHOLD:
            await self._publish_negative(stream, sk, run_id)
            await self._publish_progress(redis_client, run_id, "No matching fact-checks found")
            return

        # Publish match observations
        await self._publish_match(stream, sk, run_id, best_match, best_score)

        source_name = _first_review(best_match).get("publisher", {}).get("name", "Unknown")
        await self._publish_progress(
            redis_client, run_id, f"Found matching fact-check from {source_name}"
        )

    async def _call_api(self, query: str) -> list[dict]:
        """Query Google Fact Check Tools API. Retries once on 429."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(API_URL, params={"query": query, "key": self._api_key})

            if resp.status_code == 429:
                # Rate limited -- retry once after 2s
                await asyncio.sleep(2)
                resp = await client.get(API_URL, params={"query": query, "key": self._api_key})

            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}")

            data = resp.json()
            return data.get("claims", [])

    def _score_matches(self, results: list[dict], normalized_claim: str) -> tuple[dict, float]:
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

    async def _publish_match(
        self,
        stream: ReasoningStream,
        sk: str,
        run_id: str,
        match: dict,
        score: float,
    ) -> None:
        """Publish 5 observations for a successful match."""
        review = _first_review(match)
        rating = review.get("textualRating", "Unknown")
        publisher = review.get("publisher", {}).get("name", "Unknown")
        url = review.get("url", "")
        system = publisher.upper().replace(" ", "_")

        # 1. CLAIMREVIEW_MATCH
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CLAIMREVIEW_MATCH,
            value="TRUE^Match Found^FCK",
            value_type=ValueType.CWE,
            method="lookup_claimreview",
        )

        # 2. CLAIMREVIEW_VERDICT
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CLAIMREVIEW_VERDICT,
            value=f"{rating.upper().replace(' ', '_')}^{rating}^{system}",
            value_type=ValueType.CWE,
            method="lookup_claimreview",
        )

        # 3. CLAIMREVIEW_SOURCE
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CLAIMREVIEW_SOURCE,
            value=publisher,
            value_type=ValueType.ST,
            method="lookup_claimreview",
        )

        # 4. CLAIMREVIEW_URL
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CLAIMREVIEW_URL,
            value=url or "N/A",
            value_type=ValueType.ST,
            method="lookup_claimreview",
        )

        # 5. CLAIMREVIEW_MATCH_SCORE
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CLAIMREVIEW_MATCH_SCORE,
            value=f"{score:.2f}",
            value_type=ValueType.NM,
            method="compute_similarity",
            units="score",
            reference_range="0.0-1.0",
        )

    async def _publish_negative(
        self,
        stream: ReasoningStream,
        sk: str,
        run_id: str,
        status: str = "F",
        note: str | None = None,
    ) -> None:
        """Publish 2 observations for no-match or error outcomes."""
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CLAIMREVIEW_MATCH,
            value="FALSE^No Match^FCK",
            value_type=ValueType.CWE,
            status=status,
            method="lookup_claimreview",
            note=note,
        )
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CLAIMREVIEW_MATCH_SCORE,
            value="0.0",
            value_type=ValueType.NM,
            status=status,
            method="compute_similarity",
            units="score",
            reference_range="0.0-1.0",
        )


# Agent registry integration
_HANDLER: ClaimReviewMatcherHandler | None = None


def get_handler() -> ClaimReviewMatcherHandler:
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = ClaimReviewMatcherHandler()
    return _HANDLER
