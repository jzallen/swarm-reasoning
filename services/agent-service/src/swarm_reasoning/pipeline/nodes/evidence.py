"""Evidence pipeline node (M2.1) -- fact-check lookups and domain evidence.

Ports tool logic from ``agents/evidence/`` and ``agents/domain_evidence/``
to the LangGraph pipeline.  Reads input from PipelineState instead of Redis
Streams.  Publishes observations as side-effects via PipelineContext and
returns state updates for downstream nodes.

Four tools:

1. :func:`search_factchecks` -- Google Fact Check API lookup + TF-IDF scoring
2. :func:`lookup_domain_sources` -- domain → authoritative-source routing
3. :func:`fetch_source_content` -- HTTP content retrieval with retry
4. :func:`score_evidence` -- relevance, alignment, and confidence scoring
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from langgraph.types import RunnableConfig

from swarm_reasoning.agents._utils import STOP_WORDS, cosine_similarity, resilient_get
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

AGENT_NAME = "evidence"

# ---------------------------------------------------------------------------
# Constants (ported from agents/evidence/tools.py and agents/domain_evidence/tools.py)
# ---------------------------------------------------------------------------

_FACTCHECK_API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
_MATCH_THRESHOLD = 0.50

_NEGATION_PATTERNS = re.compile(
    r"\b(not|no evidence|false|debunked|misleading|incorrect|disproven|unfounded)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Domain routes (lazy-loaded from agents/domain_evidence/routes.json)
# ---------------------------------------------------------------------------

_routes_cache: dict[str, list[dict]] | None = None


def _load_routes() -> dict[str, list[dict]]:
    """Load and cache the domain routing table."""
    global _routes_cache
    if _routes_cache is None:
        routes_path = Path(__file__).parents[2] / "agents" / "domain_evidence" / "routes.json"
        with open(routes_path) as f:
            _routes_cache = json.load(f)
    return _routes_cache


# ===================================================================
# Tool 1: search_factchecks
# ===================================================================


def _build_factcheck_query(claim: str, persons: list[str], organizations: list[str]) -> str:
    """Build API query from normalized claim and top entities."""
    parts: list[str] = []
    for name in (persons + organizations)[:2]:
        parts.append(name)
    parts.append(claim)
    return " ".join(parts)[:100]


async def _call_factcheck_api(query: str, api_key: str) -> list[dict]:
    """Query Google Fact Check Tools API with single retry on 429."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_FACTCHECK_API_URL, params={"query": query, "key": api_key})
        if resp.status_code == 429:
            await asyncio.sleep(2)
            resp = await client.get(_FACTCHECK_API_URL, params={"query": query, "key": api_key})
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code}", request=resp.request, response=resp
            )
        return resp.json().get("claims", [])


def _first_review(result: dict) -> dict:
    """Return the first ClaimReview entry, or ``{}``."""
    return result.get("claimReview", [{}])[0]


def _score_factcheck_matches(results: list[dict], normalized_claim: str) -> tuple[dict, float]:
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


async def _publish_negative_claimreview(
    ctx: PipelineContext, *, status: str = "F", note: str | None = None
) -> None:
    """Publish 2 observations for no-match or error outcomes."""
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIMREVIEW_MATCH,
        value="FALSE^No Match^FCK",
        value_type=ValueType.CWE,
        status=status,
        method="lookup_claimreview",
        note=note,
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIMREVIEW_MATCH_SCORE,
        value="0.0",
        value_type=ValueType.NM,
        status=status,
        method="compute_similarity",
        units="score",
        reference_range="0.0-1.0",
    )


async def search_factchecks(
    normalized_claim: str,
    persons: list[str],
    organizations: list[str],
    ctx: PipelineContext,
) -> list[dict]:
    """Search Google Fact Check API and publish CLAIMREVIEW_* observations.

    Returns a list of match dicts for ``PipelineState.claimreview_matches``.
    Each dict has keys: ``source``, ``rating``, ``url``, ``score``.
    Returns an empty list when no matches are found or on error.
    """
    api_key = os.environ.get("GOOGLE_FACTCHECK_API_KEY", "")
    if not api_key:
        logger.warning("GOOGLE_FACTCHECK_API_KEY not configured")
        await _publish_negative_claimreview(ctx, status="X", note="API key not configured")
        return []

    query = _build_factcheck_query(normalized_claim, persons, organizations)

    try:
        results = await _call_factcheck_api(query, api_key)
    except Exception as exc:
        logger.warning("ClaimReview API error: %s", exc)
        await _publish_negative_claimreview(ctx, status="X", note=f"API error: {exc}")
        return []

    if not results:
        await _publish_negative_claimreview(ctx)
        return []

    best_match, best_score = _score_factcheck_matches(results, normalized_claim)

    if best_score < _MATCH_THRESHOLD:
        await _publish_negative_claimreview(ctx)
        return []

    # Publish 5 observations for a successful match
    review = _first_review(best_match)
    rating = review.get("textualRating", "Unknown")
    publisher = review.get("publisher", {}).get("name", "Unknown")
    url = review.get("url", "")
    system = publisher.upper().replace(" ", "_")

    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIMREVIEW_MATCH,
        value="TRUE^Match Found^FCK",
        value_type=ValueType.CWE,
        method="lookup_claimreview",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIMREVIEW_VERDICT,
        value=f"{rating.upper().replace(' ', '_')}^{rating}^{system}",
        value_type=ValueType.CWE,
        method="lookup_claimreview",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIMREVIEW_SOURCE,
        value=publisher,
        value_type=ValueType.ST,
        method="lookup_claimreview",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIMREVIEW_URL,
        value=url or "N/A",
        value_type=ValueType.ST,
        method="lookup_claimreview",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIMREVIEW_MATCH_SCORE,
        value=f"{best_score:.2f}",
        value_type=ValueType.NM,
        method="compute_similarity",
        units="score",
        reference_range="0.0-1.0",
    )

    return [
        {
            "source": publisher,
            "rating": rating,
            "url": url,
            "score": round(best_score, 2),
        }
    ]


# ===================================================================
# Tool 2: lookup_domain_sources
# ===================================================================


def lookup_domain_sources(domain: str) -> list[dict]:
    """Look up authoritative sources for a claim domain.

    Args:
        domain: Domain category (HEALTHCARE, ECONOMICS, POLICY, SCIENCE,
                ELECTION, CRIME, OTHER).  Case-insensitive.

    Returns:
        List of source dicts with ``name`` and ``url_template`` keys,
        ordered by priority (prefer earlier entries).
    """
    routes = _load_routes()
    key = domain.upper() if domain else "OTHER"
    return routes.get(key, routes.get("OTHER", []))


# ===================================================================
# Tool 3: fetch_source_content
# ===================================================================


async def fetch_source_content(url: str) -> str:
    """Fetch text content from an authoritative source URL.

    Returns the first 2000 characters on success, or an error string
    prefixed with ``ERROR:`` on failure.
    """
    try:
        resp = await resilient_get(url, follow_redirects=True, max_redirects=5)
        if resp.status_code >= 400:
            return f"ERROR: HTTP {resp.status_code} from {url}"
        return resp.text[:2000]
    except Exception as exc:
        logger.warning("fetch_source_content failed for %s: %s", url, exc)
        return f"ERROR: Failed to fetch {url}: {exc}"


# ===================================================================
# Tool 4: score_evidence
# ===================================================================


def score_evidence(
    content: str,
    normalized_claim: str,
    *,
    fallback_depth: int = 0,
    source_is_old: bool = False,
    is_indirect: bool = False,
) -> tuple[str, float]:
    """Score evidence alignment and compute confidence.

    Combines relevance checking, keyword-overlap alignment scoring, and
    penalty-based confidence computation into a single call.

    Args:
        content: Fetched source content.
        normalized_claim: The normalized claim text.
        fallback_depth: Number of fallback sources tried before finding
            content (0 = primary source).  Each step costs −0.10.
        source_is_old: ``True`` if source is >2 years old (−0.15).
        is_indirect: ``True`` if source is indirect/secondary (−0.20).

    Returns:
        ``(alignment_cwe, confidence)`` where *alignment_cwe* is a CWE
        string (e.g. ``"SUPPORTS^Supports Claim^FCK"``) and *confidence*
        is a float in ``[0.0, 1.0]``.
    """
    if not content or content.startswith("ERROR:"):
        return "ABSENT^No Evidence Found^FCK", 0.0

    claim_keywords = set(normalized_claim.lower().split()) - STOP_WORDS
    if not claim_keywords:
        return "ABSENT^No Evidence Found^FCK", 0.0

    content_lower = content[:500].lower()
    matching = sum(1 for kw in claim_keywords if kw in content_lower)
    overlap_ratio = matching / len(claim_keywords)
    has_negation = bool(_NEGATION_PATTERNS.search(content_lower))

    if overlap_ratio >= 0.6 and not has_negation:
        alignment = "SUPPORTS^Supports Claim^FCK"
    elif overlap_ratio >= 0.6 and has_negation:
        alignment = "CONTRADICTS^Contradicts Claim^FCK"
    elif overlap_ratio >= 0.3:
        alignment = "PARTIAL^Partially Supports^FCK"
    else:
        alignment = "ABSENT^No Evidence Found^FCK"

    # Confidence computation
    if "ABSENT" in alignment:
        return alignment, 0.0

    confidence = 1.0
    confidence -= 0.10 * fallback_depth
    if source_is_old:
        confidence -= 0.15
    if is_indirect:
        confidence -= 0.20
    if "PARTIAL" in alignment:
        confidence -= 0.10

    return alignment, round(max(0.10, confidence), 2)


# ===================================================================
# Node function
# ===================================================================


def _build_search_query(normalized_claim: str, persons: list[str], organizations: list[str]) -> str:
    """Build a search query from claim context for domain source URLs."""
    parts: list[str] = []
    for name in (persons + organizations)[:2]:
        parts.append(name)
    claim_keywords = [w for w in normalized_claim.lower().split() if w not in STOP_WORDS]
    parts.extend(claim_keywords)
    query = " ".join(parts)
    if len(query) <= 80:
        return query
    truncated = query[:80]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated


async def evidence_node(state: PipelineState, config: RunnableConfig) -> dict:
    """Evidence pipeline node: fact-check lookups and domain evidence research.

    Orchestrates the 4 evidence tools:

    1. Searches Google Fact Check API for existing reviews
    2. Looks up authoritative domain sources for the claim domain
    3. Fetches content from sources (tries each until success)
    4. Scores evidence alignment and confidence

    Publishes CLAIMREVIEW_* and DOMAIN_* observations via PipelineContext.

    Returns:
        State updates for ``claimreview_matches``, ``domain_sources``,
        ``evidence_confidence``, and ``observations``.
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat(AGENT_NAME)

    normalized_claim = state.get("normalized_claim") or state.get("claim_text", "")
    claim_domain = state.get("claim_domain") or "OTHER"
    entities: dict[str, list[str]] = state.get("entities") or {}
    persons: list[str] = entities.get("persons", [])
    organizations: list[str] = entities.get("orgs", [])

    await ctx.publish_progress(AGENT_NAME, "Gathering evidence...")

    # --- Tool 1: Search factchecks ---
    ctx.heartbeat(AGENT_NAME)
    claimreview_matches = await search_factchecks(normalized_claim, persons, organizations, ctx)

    # --- Tool 2: Lookup domain sources ---
    sources = lookup_domain_sources(claim_domain)

    # --- Tool 3: Fetch source content (iterate until first success) ---
    ctx.heartbeat(AGENT_NAME)
    source_name = "N/A"
    source_url = "N/A"
    content = ""
    fallback_depth = 0
    search_query = _build_search_query(normalized_claim, persons, organizations)

    for i, source in enumerate(sources):
        url_template = source.get("url_template", "")
        url = url_template.format(query=quote_plus(search_query))
        fetched = await fetch_source_content(url)

        if not fetched.startswith("ERROR:"):
            source_name = source.get("name", "Unknown")
            source_url = url
            content = fetched
            fallback_depth = i
            break
        fallback_depth = i

    # --- Tool 4: Score evidence ---
    alignment, confidence = score_evidence(content, normalized_claim, fallback_depth=fallback_depth)

    # Publish DOMAIN_* observations
    ctx.heartbeat(AGENT_NAME)
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.DOMAIN_SOURCE_NAME,
        value=source_name,
        value_type=ValueType.ST,
        method="lookup_domain_sources",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.DOMAIN_SOURCE_URL,
        value=source_url,
        value_type=ValueType.ST,
        method="lookup_domain_sources",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT,
        value=alignment,
        value_type=ValueType.CWE,
        method="score_claim_alignment",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.DOMAIN_CONFIDENCE,
        value=f"{confidence:.2f}",
        value_type=ValueType.NM,
        method="compute_evidence_confidence",
        units="score",
        reference_range="0.0-1.0",
    )

    domain_sources = [
        {
            "name": source_name,
            "url": source_url,
            "alignment": alignment.split("^")[0],
            "confidence": confidence,
        }
    ]

    match_desc = (
        f"found {len(claimreview_matches)} match(es)" if claimreview_matches else "no matches"
    )
    await ctx.publish_progress(
        AGENT_NAME,
        f"Evidence complete: ClaimReview {match_desc}, "
        f"domain source={source_name}, alignment={alignment.split('^')[0]}",
    )

    return {
        "claimreview_matches": claimreview_matches,
        "domain_sources": domain_sources,
        "evidence_confidence": confidence,
        "observations": [
            {"agent": AGENT_NAME, "code": "DOMAIN_SOURCE_NAME", "value": source_name},
            {"agent": AGENT_NAME, "code": "DOMAIN_SOURCE_URL", "value": source_url},
            {
                "agent": AGENT_NAME,
                "code": "DOMAIN_EVIDENCE_ALIGNMENT",
                "value": alignment,
            },
            {
                "agent": AGENT_NAME,
                "code": "DOMAIN_CONFIDENCE",
                "value": f"{confidence:.2f}",
            },
        ],
    }
