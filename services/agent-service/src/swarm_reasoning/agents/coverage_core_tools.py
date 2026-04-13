"""Coverage agent @tool definitions for LangChain agents (ADR-004).

Wraps the pure functions from coverage_core.py as @tool-decorated functions.
Each tool combines computation with observation publishing via AgentContext,
matching the claim-detector tool pattern. Used by CoverageHandler and
available for future LangGraph ReAct agent migration.
"""

from __future__ import annotations

import json
import os
from typing import Annotated

import httpx
from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.coverage_core import (
    NEWSAPI_URL,
    build_search_query,
    classify_framing,
    compute_compound_sentiment,
    select_top_source,
)
from swarm_reasoning.agents.fanout_base import ClaimContext
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


@tool
async def search_coverage(
    query: str,
    source_ids: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Search NewsAPI for articles from specific sources and publish the article count.

    Queries the NewsAPI /v2/everything endpoint for articles matching the query
    from the given comma-separated source IDs. Publishes a COVERAGE_ARTICLE_COUNT
    observation with the number of articles found.

    Args:
        query: The search query string (from build_coverage_query).
        source_ids: Comma-separated NewsAPI source IDs (e.g. "msnbc,cnn").
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        JSON string with article_count and articles array.
    """
    api_key = os.environ.get("NEWSAPI_KEY", "")
    if not api_key:
        # Publish X-status observations for missing API key
        await context.publish_obs(
            code=ObservationCode.COVERAGE_ARTICLE_COUNT,
            value="0",
            value_type=ValueType.NM,
            status="X",
            method="search_newsapi",
            note="API key not configured",
            units="count",
        )
        await context.publish_obs(
            code=ObservationCode.COVERAGE_FRAMING,
            value="ABSENT^Not Covered^FCK",
            value_type=ValueType.CWE,
            status="X",
            method="detect_framing",
        )
        return json.dumps({"article_count": 0, "articles": [], "error": "API key not configured"})

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
                import asyncio
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
        # Publish X-status observations for API error
        await context.publish_obs(
            code=ObservationCode.COVERAGE_ARTICLE_COUNT,
            value="0",
            value_type=ValueType.NM,
            status="X",
            method="search_newsapi",
            note=f"API error: {exc}",
            units="count",
        )
        await context.publish_obs(
            code=ObservationCode.COVERAGE_FRAMING,
            value="ABSENT^Not Covered^FCK",
            value_type=ValueType.CWE,
            status="X",
            method="detect_framing",
        )
        return json.dumps({"article_count": 0, "articles": [], "error": str(exc)})

    # Publish COVERAGE_ARTICLE_COUNT
    await context.publish_obs(
        code=ObservationCode.COVERAGE_ARTICLE_COUNT,
        value=str(len(articles)),
        value_type=ValueType.NM,
        method="search_newsapi",
        units="count",
    )

    return json.dumps({"article_count": len(articles), "articles": articles})


@tool
async def detect_coverage_framing(
    headlines_json: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Analyze headline sentiment and publish the coverage framing observation.

    Computes a VADER-style compound sentiment score from the headlines and
    classifies it into SUPPORTIVE, CRITICAL, or NEUTRAL framing. If no
    headlines are provided, publishes ABSENT framing. Publishes a
    COVERAGE_FRAMING observation.

    Args:
        headlines_json: JSON array of headline strings (e.g. '["headline1", ...]').
                        Pass "[]" for zero-article coverage (ABSENT framing).
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        JSON string with compound score and CWE-formatted framing value.
    """
    headlines = json.loads(headlines_json)

    if not headlines:
        framing = "ABSENT^Not Covered^FCK"
        await context.publish_obs(
            code=ObservationCode.COVERAGE_FRAMING,
            value=framing,
            value_type=ValueType.CWE,
            method="detect_framing",
        )
        return json.dumps({"compound": 0.0, "framing": framing})

    compound = compute_compound_sentiment(headlines)
    framing = classify_framing(compound)

    await context.publish_obs(
        code=ObservationCode.COVERAGE_FRAMING,
        value=framing,
        value_type=ValueType.CWE,
        method="detect_framing",
    )

    return json.dumps({"compound": compound, "framing": framing})


@tool
async def find_top_coverage_source(
    articles_json: str,
    sources_json: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Select the highest-credibility source and publish source observations.

    Finds the article from the most credible source (by credibility_rank)
    and publishes COVERAGE_TOP_SOURCE and COVERAGE_TOP_SOURCE_URL observations.

    Args:
        articles_json: JSON array of article objects from NewsAPI.
        sources_json: JSON array of source objects with id, name, credibility_rank.
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        JSON string with source name and URL, or null fields if no articles.
    """
    articles = json.loads(articles_json)
    sources = json.loads(sources_json)
    top = select_top_source(articles, sources)

    if top:
        name, url = top
        await context.publish_obs(
            code=ObservationCode.COVERAGE_TOP_SOURCE,
            value=name,
            value_type=ValueType.ST,
            method="select_top_source",
        )
        await context.publish_obs(
            code=ObservationCode.COVERAGE_TOP_SOURCE_URL,
            value=url,
            value_type=ValueType.ST,
            method="select_top_source",
        )
        return json.dumps({"name": name, "url": url})

    return json.dumps({"name": None, "url": None})


@tool
def build_coverage_query(normalized_claim: str) -> str:
    """Build an optimized NewsAPI search query from a normalized claim.

    Removes common stop words and truncates to 100 characters at a word
    boundary.

    Args:
        normalized_claim: The normalized claim text.

    Returns:
        Optimized search query string (max 100 characters).
    """
    ctx = ClaimContext(normalized_claim=normalized_claim)
    return build_search_query(ctx)


# All coverage tools for binding to a LangChain agent
COVERAGE_TOOLS = [
    build_coverage_query,
    search_coverage,
    detect_coverage_framing,
    find_top_coverage_source,
]
