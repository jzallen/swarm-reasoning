"""Coverage pipeline node (M3.2) -- parameterized left/center/right news analysis.

Runs three spectrum-specific coverage analyses concurrently using shared,
parameterized tool functions.  Each spectrum loads its own source list,
queries NewsAPI, computes headline sentiment framing, and selects the
highest-credibility source.

Four parameterized tools (each takes ``spectrum`` / ``agent_name``):

1. :func:`build_search_query`       -- stop-word removal + truncation
2. :func:`search_coverage`          -- NewsAPI query + COVERAGE_ARTICLE_COUNT obs
3. :func:`detect_coverage_framing`  -- VADER-style sentiment → COVERAGE_FRAMING obs
4. :func:`find_top_coverage_source` -- credibility ranking → COVERAGE_TOP_SOURCE obs

The node entry point :func:`coverage_node` fans out all three spectrums via
``asyncio.gather`` and merges results into ``coverage_left``,
``coverage_center``, ``coverage_right``, and ``framing_analysis``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
from langgraph.types import RunnableConfig

from swarm_reasoning.agents._utils import STOP_WORDS
from swarm_reasoning.agents.coverage.core import (
    NEWSAPI_URL,
    classify_framing,
    compute_compound_sentiment,
    select_top_source,
)
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

# Spectrum → agent name mapping
_SPECTRUMS = {
    "left": "coverage-left",
    "center": "coverage-center",
    "right": "coverage-right",
}

# Spectrum → PipelineState key mapping
_STATE_KEYS = {
    "left": "coverage_left",
    "center": "coverage_center",
    "right": "coverage_right",
}

# ---------------------------------------------------------------------------
# Source loading (lazy-cached per spectrum)
# ---------------------------------------------------------------------------

_sources_cache: dict[str, list[dict]] = {}


def _load_sources(spectrum: str) -> list[dict]:
    """Load and cache the source list for a given spectrum."""
    if spectrum not in _sources_cache:
        sources_path = (
            Path(__file__).parents[2] / "agents" / "coverage" / "sources" / f"{spectrum}.json"
        )
        with open(sources_path) as f:
            _sources_cache[spectrum] = json.load(f)
    return _sources_cache[spectrum]


# ===================================================================
# Tool 1: build_search_query
# ===================================================================


def build_search_query(normalized_claim: str) -> str:
    """Build an optimized NewsAPI search query from a normalized claim.

    Removes stop words and truncates to 100 characters at a word boundary.
    """
    words = normalized_claim.lower().split()
    filtered = [w for w in words if w not in STOP_WORDS]
    query = " ".join(filtered)

    if len(query) <= 100:
        return query

    truncated = query[:100]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated


# ===================================================================
# Tool 2: search_coverage
# ===================================================================


async def search_coverage(
    query: str,
    source_ids: str,
    ctx: PipelineContext,
    agent_name: str,
) -> list[dict]:
    """Search NewsAPI for articles from specific sources.

    Publishes COVERAGE_ARTICLE_COUNT observation. Returns list of article dicts.
    On error or missing API key, publishes X-status observations and returns [].
    """
    api_key = os.environ.get("NEWSAPI_KEY", "")
    if not api_key:
        logger.warning("NEWSAPI_KEY not configured for %s", agent_name)
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_ARTICLE_COUNT,
            value="0",
            value_type=ValueType.NM,
            status="X",
            method="search_newsapi",
            note="API key not configured",
            units="count",
        )
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_FRAMING,
            value="ABSENT^Not Covered^FCK",
            value_type=ValueType.CWE,
            status="X",
            method="detect_framing",
        )
        return []

    params = {
        "q": query,
        "sources": source_ids,
        "sortBy": "relevancy",
        "pageSize": "10",
        "language": "en",
        "apiKey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(NEWSAPI_URL, params=params)
            if resp.status_code == 429:
                await asyncio.sleep(1)
                resp = await client.get(NEWSAPI_URL, params=params)

            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )

            data = resp.json()
            articles = data.get("articles", [])
    except Exception as exc:
        logger.warning("NewsAPI error for %s: %s", agent_name, exc)
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_ARTICLE_COUNT,
            value="0",
            value_type=ValueType.NM,
            status="X",
            method="search_newsapi",
            note=f"API error: {exc}",
            units="count",
        )
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_FRAMING,
            value="ABSENT^Not Covered^FCK",
            value_type=ValueType.CWE,
            status="X",
            method="detect_framing",
        )
        return []

    await ctx.publish_observation(
        agent=agent_name,
        code=ObservationCode.COVERAGE_ARTICLE_COUNT,
        value=str(len(articles)),
        value_type=ValueType.NM,
        method="search_newsapi",
        units="count",
    )

    return articles


# ===================================================================
# Tool 3: detect_coverage_framing
# ===================================================================


async def detect_coverage_framing(
    articles: list[dict],
    ctx: PipelineContext,
    agent_name: str,
) -> tuple[str, float]:
    """Analyze headline sentiment and publish COVERAGE_FRAMING observation.

    Returns (framing_cwe, compound_score).
    """
    if not articles:
        framing = "ABSENT^Not Covered^FCK"
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_FRAMING,
            value=framing,
            value_type=ValueType.CWE,
            method="detect_framing",
        )
        return framing, 0.0

    headlines = [a.get("title", "") for a in articles[:5] if a.get("title")]
    compound = compute_compound_sentiment(headlines)
    framing = classify_framing(compound)

    await ctx.publish_observation(
        agent=agent_name,
        code=ObservationCode.COVERAGE_FRAMING,
        value=framing,
        value_type=ValueType.CWE,
        method="detect_framing",
    )

    return framing, compound


# ===================================================================
# Tool 4: find_top_coverage_source
# ===================================================================


async def find_top_coverage_source(
    articles: list[dict],
    sources: list[dict],
    ctx: PipelineContext,
    agent_name: str,
) -> dict | None:
    """Select the highest-credibility source and publish observations.

    Returns a dict with ``name`` and ``url``, or None if no articles.
    """
    top = select_top_source(articles, sources)

    if top:
        name, url = top
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_TOP_SOURCE,
            value=name,
            value_type=ValueType.ST,
            method="select_top_source",
        )
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_TOP_SOURCE_URL,
            value=url,
            value_type=ValueType.ST,
            method="select_top_source",
        )
        return {"name": name, "url": url}

    return None


# ===================================================================
# Per-spectrum runner
# ===================================================================


async def _run_spectrum(
    spectrum: str,
    normalized_claim: str,
    ctx: PipelineContext,
) -> tuple[str, list[dict], str, float]:
    """Run the 4-tool coverage pipeline for a single spectrum.

    Returns (state_key, articles_with_metadata, framing_cwe, compound).
    """
    agent_name = _SPECTRUMS[spectrum]
    state_key = _STATE_KEYS[spectrum]
    sources = _load_sources(spectrum)

    await ctx.publish_progress(agent_name, f"Searching {spectrum}-spectrum sources...")

    # Tool 1: Build query
    query = build_search_query(normalized_claim)

    # Tool 2: Search coverage
    source_ids = ",".join(s["id"] for s in sources[:20])
    articles = await search_coverage(query, source_ids, ctx, agent_name)
    ctx.heartbeat(agent_name)

    # Tool 3: Detect framing
    framing, compound = await detect_coverage_framing(articles, ctx, agent_name)
    ctx.heartbeat(agent_name)

    # Tool 4: Find top source
    top_source = await find_top_coverage_source(articles, sources, ctx, agent_name)
    ctx.heartbeat(agent_name)

    # Build article list for state
    coverage_articles = []
    for article in articles:
        coverage_articles.append({
            "title": article.get("title", ""),
            "url": article.get("url", ""),
            "source": article.get("source", {}).get("name", ""),
            "framing": framing.split("^")[0],
        })

    if top_source:
        match_desc = f"{len(articles)} article(s), top={top_source['name']}"
    else:
        match_desc = f"{len(articles)} article(s)"
    await ctx.publish_progress(
        agent_name,
        f"Coverage complete: {match_desc}, framing={framing.split('^')[0]}",
    )

    return state_key, coverage_articles, framing, compound


# ===================================================================
# Node function
# ===================================================================


async def coverage_node(state: PipelineState, config: RunnableConfig) -> dict:
    """Coverage pipeline node: parameterized left/center/right news analysis.

    Runs three spectrum-specific analyses concurrently via asyncio.gather.
    Each spectrum executes the same 4-tool pipeline with spectrum-specific
    sources. Publishes COVERAGE_* observations per spectrum via PipelineContext.

    Returns:
        State updates for ``coverage_left``, ``coverage_center``,
        ``coverage_right``, ``framing_analysis``, and ``observations``.
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat("coverage")

    normalized_claim = state.get("normalized_claim") or state.get("claim_text", "")

    await ctx.publish_progress("coverage", "Starting coverage analysis (left/center/right)...")

    # Run all three spectrums concurrently
    results = await asyncio.gather(
        _run_spectrum("left", normalized_claim, ctx),
        _run_spectrum("center", normalized_claim, ctx),
        _run_spectrum("right", normalized_claim, ctx),
    )

    # Unpack results
    state_updates: dict = {}
    framing_analysis: dict[str, dict] = {}
    all_observations: list[dict] = []

    for state_key, articles, framing, compound in results:
        spectrum = state_key.replace("coverage_", "")
        agent_name = _SPECTRUMS[spectrum]

        state_updates[state_key] = articles

        framing_analysis[spectrum] = {
            "framing": framing.split("^")[0],
            "compound": compound,
            "article_count": len(articles),
        }

        all_observations.extend([
            {
                "agent": agent_name,
                "code": "COVERAGE_ARTICLE_COUNT",
                "value": str(len(articles)),
            },
            {
                "agent": agent_name,
                "code": "COVERAGE_FRAMING",
                "value": framing,
            },
        ])

    state_updates["framing_analysis"] = framing_analysis
    state_updates["observations"] = all_observations

    total = sum(fa["article_count"] for fa in framing_analysis.values())
    await ctx.publish_progress(
        "coverage",
        f"Coverage complete: {total} total articles across 3 spectrums",
    )

    return state_updates
