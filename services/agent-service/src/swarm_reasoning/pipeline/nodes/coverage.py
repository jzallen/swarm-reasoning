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
from pathlib import Path

from langgraph.types import RunnableConfig

from swarm_reasoning.agents.coverage.tools import (
    build_search_query,
    detect_coverage_framing,
    find_top_coverage_source,
    search_coverage,
)
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
