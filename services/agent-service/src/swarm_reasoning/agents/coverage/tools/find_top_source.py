"""Coverage tool: select the highest-credibility source from articles.

Publishes COVERAGE_TOP_SOURCE and COVERAGE_TOP_SOURCE_URL observations.
"""

from __future__ import annotations

from swarm_reasoning.agents.coverage.core import select_top_source
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext


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
