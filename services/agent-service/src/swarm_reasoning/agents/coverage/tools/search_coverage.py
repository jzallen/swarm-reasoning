"""Coverage tool: search NewsAPI for articles from specific sources.

Publishes COVERAGE_ARTICLE_COUNT observation. On error or missing API key,
publishes X-status observations for both article count and framing.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

from swarm_reasoning.agents.coverage.core import NEWSAPI_URL
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


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
