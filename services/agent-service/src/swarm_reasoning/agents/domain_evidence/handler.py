"""Domain-evidence agent handler -- authoritative domain source research.

Routes to domain-specific authoritative sources based on CLAIM_DOMAIN,
fetches content, scores alignment and confidence, publishes 4 observations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus

import httpx
import redis.asyncio as aioredis

from swarm_reasoning.agents.fanout_base import ClaimContext, FanoutBase
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "domain-evidence"

# Stop words for query derivation
_STOP_WORDS = frozenset(
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
        "and",
        "but",
        "or",
        "not",
        "that",
        "this",
        "it",
        "its",
    }
)

# Negation patterns for alignment detection
_NEGATION_PATTERNS = re.compile(
    r"\b(not|no evidence|false|debunked|misleading|incorrect|disproven|unfounded)\b",
    re.IGNORECASE,
)


def _load_routes() -> dict[str, list[dict]]:
    """Load domain routing table."""
    routes_path = Path(__file__).parent / "routes.json"
    with open(routes_path) as f:
        return json.load(f)


def derive_query(context: ClaimContext) -> str:
    """Derive search query from claim and entities.

    Prepends entity names for specificity, appends statistics verbatim.
    Truncates to 80 chars at word boundary.
    """
    parts: list[str] = []

    # Prepend prominent entity names
    for name in (context.persons + context.organizations)[:3]:
        parts.append(name)

    # Add claim text minus stop words
    words = context.normalized_claim.lower().split()
    filtered = [w for w in words if w not in _STOP_WORDS]
    parts.extend(filtered)

    # Append statistics verbatim
    for stat in context.statistics[:2]:
        parts.append(stat)

    # Append dates
    for date in context.dates[:1]:
        parts.append(date)

    query = " ".join(parts)

    if len(query) <= 80:
        return query

    truncated = query[:80]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space]
    return truncated


def score_alignment(content: str, context: ClaimContext) -> str:
    """Score how well source content aligns with the claim.

    Uses keyword overlap + negation detection.
    Returns CWE-formatted alignment value.
    """
    if not content:
        return "ABSENT^No Evidence Found^FCK"

    # Extract claim keywords
    claim_words = set(context.normalized_claim.lower().split())
    claim_keywords = claim_words - _STOP_WORDS
    if not claim_keywords:
        return "ABSENT^No Evidence Found^FCK"

    # Check content (title + first 500 chars)
    content_lower = content[:500].lower()
    matching = sum(1 for kw in claim_keywords if kw in content_lower)
    overlap_ratio = matching / len(claim_keywords)

    # Check for negation
    has_negation = bool(_NEGATION_PATTERNS.search(content_lower))

    if overlap_ratio >= 0.6 and not has_negation:
        return "SUPPORTS^Supports Claim^FCK"
    elif overlap_ratio >= 0.6 and has_negation:
        return "CONTRADICTS^Contradicts Claim^FCK"
    elif overlap_ratio >= 0.3:
        return "PARTIAL^Partially Supports^FCK"
    else:
        return "ABSENT^No Evidence Found^FCK"


def score_confidence(
    alignment: str,
    fallback_depth: int = 0,
    source_is_old: bool = False,
    is_indirect: bool = False,
) -> float:
    """Compute confidence score with penalty factors.

    Base = 1.0, penalized by:
    - Fallback: -0.10 per step
    - Old source (>2yr): -0.15
    - Indirect source: -0.20
    - PARTIAL alignment: -0.10
    - ABSENT alignment: confidence = 0.0
    """
    if "ABSENT" in alignment:
        return 0.0

    confidence = 1.0

    # Fallback penalty
    confidence -= 0.10 * fallback_depth

    # Age penalty
    if source_is_old:
        confidence -= 0.15

    # Indirect source penalty
    if is_indirect:
        confidence -= 0.20

    # Partial alignment penalty
    if "PARTIAL" in alignment:
        confidence -= 0.10

    # Floor at 0.10 for non-absent
    return max(0.10, confidence)


def _is_relevant(content: str, context: ClaimContext) -> bool:
    """Check if content is relevant by checking entity/keyword presence."""
    if not content:
        return False

    content_lower = content[:1000].lower()

    # Check for entity presence
    for name in context.persons + context.organizations:
        if name.lower() in content_lower:
            return True

    # Check for claim keyword presence
    claim_words = set(context.normalized_claim.lower().split()) - _STOP_WORDS
    matches = sum(1 for w in claim_words if w in content_lower)
    return matches >= 2


class DomainEvidenceHandler(FanoutBase):
    """Routes to authoritative domain sources and scores alignment."""

    AGENT_NAME = AGENT_NAME

    def __init__(self, redis_config: RedisConfig | None = None) -> None:
        super().__init__(redis_config)
        self._routes = _load_routes()

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        query = derive_query(context)
        domain = context.domain.upper()
        sources = self._routes.get(domain, self._routes.get("OTHER", []))

        await self._publish_progress(redis_client, run_id, "Consulting domain sources...")

        # Try sources in priority order (max 2 attempts)
        source_name = "N/A"
        source_url = "N/A"
        content = ""
        fallback_depth = 0

        for i, source in enumerate(sources[:3]):
            url = source["url_template"].format(query=quote_plus(query))
            try:
                fetched = await self._fetch_source(url)
            except Exception:
                fallback_depth = i + 1
                continue

            if fetched and _is_relevant(fetched, context):
                source_name = source["name"]
                source_url = url
                content = fetched
                fallback_depth = i
                break
            fallback_depth = i + 1

        # Score alignment and confidence
        alignment = score_alignment(content, context)
        confidence = score_confidence(alignment, fallback_depth=fallback_depth)

        if source_name != "N/A":
            await self._publish_progress(redis_client, run_id, f"Found evidence from {source_name}")
        else:
            await self._publish_progress(redis_client, run_id, "No relevant domain sources found")

        # Publish 4 observations (always, with N/A for absent)
        # 1. DOMAIN_SOURCE_NAME
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.DOMAIN_SOURCE_NAME,
            value=source_name,
            value_type=ValueType.ST,
            method="route_domain_source",
        )

        # 2. DOMAIN_SOURCE_URL
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.DOMAIN_SOURCE_URL,
            value=source_url,
            value_type=ValueType.ST,
            method="route_domain_source",
        )

        # 3. DOMAIN_EVIDENCE_ALIGNMENT
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT,
            value=alignment,
            value_type=ValueType.CWE,
            method="score_alignment",
        )

        # 4. DOMAIN_CONFIDENCE
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.DOMAIN_CONFIDENCE,
            value=f"{confidence:.2f}",
            value_type=ValueType.NM,
            method="score_confidence",
            units="score",
            reference_range="0.0-1.0",
        )

    async def _fetch_source(self, url: str) -> str | None:
        """Fetch content from URL with 10s timeout. Returns text or None."""
        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=True, max_redirects=5
        ) as client:
            resp = await client.get(url)

            if resp.status_code == 429:
                await asyncio.sleep(1)
                resp = await client.get(url)

            if resp.status_code >= 500:
                # Retry once for 5xx
                await asyncio.sleep(1)
                resp = await client.get(url)

            if resp.status_code >= 400:
                return None

            return resp.text


# Agent registry integration
_HANDLER: DomainEvidenceHandler | None = None


def get_handler() -> DomainEvidenceHandler:
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = DomainEvidenceHandler()
    return _HANDLER
