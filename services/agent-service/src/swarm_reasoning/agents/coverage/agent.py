"""Coverage agent -- spectrum-parameterized news coverage analysis.

Uses create_react_agent from LangGraph to let the LLM search NewsAPI sources,
analyze headline sentiment, and identify top-credibility sources for a claim.
The factory function ``create_agent`` returns a compiled ReAct agent
parameterized by media spectrum (left/center/right) and source list.

Four tools:

1. ``build_query``     -- stop-word removal + truncation
2. ``search_news``     -- NewsAPI query for spectrum sources
3. ``detect_framing``  -- VADER-style headline sentiment → framing classification
4. ``find_top_source`` -- credibility-ranked source selection

Accepts CoverageInput + PipelineContext via ``run_coverage_agent``, returns
CoverageOutput.  Publishes COVERAGE_* observations via PipelineContext.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import httpx
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from swarm_reasoning.agents.coverage.core import (
    NEWSAPI_URL,
    classify_framing,
    compute_compound_sentiment,
    select_top_source,
)
from swarm_reasoning.agents.coverage.models import CoverageInput, CoverageOutput
from swarm_reasoning.agents.coverage.tools import build_search_query
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

MODEL_ID = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = (
    "You are a {spectrum}-spectrum news coverage analysis agent in a "
    "fact-checking pipeline. Your job is to find and analyze how "
    "{spectrum}-leaning media sources cover a given claim.\n\n"
    "Workflow:\n"
    "1. Build an optimized search query from the claim with build_query\n"
    "2. Search for articles from {spectrum}-spectrum sources with search_news\n"
    "3. Analyze the framing of found articles with detect_framing\n"
    "4. Identify the highest-credibility source with find_top_source\n\n"
    "Always follow this order. If no articles are found, still call "
    "detect_framing and find_top_source so they record the absence."
)


# ---------------------------------------------------------------------------
# Result accumulator -- tools write to this via closure
# ---------------------------------------------------------------------------


@dataclass
class _Results:
    """Accumulates structured results from tool invocations."""

    articles: list[dict] = field(default_factory=list)
    framing_cwe: str = "ABSENT^Not Covered^FCK"
    compound_score: float = 0.0
    top_source: dict | None = None


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def _build_tools(
    spectrum: str,
    sources: list[dict],
    input: CoverageInput,
    results: _Results,
) -> list:
    """Build LangChain tools scoped to a specific spectrum and input.

    Tools close over *spectrum* and *sources* for NewsAPI configuration,
    *input* for claim context, and *results* to accumulate structured
    output that ``run_coverage_agent`` converts to ``CoverageOutput``.
    """
    source_ids = ",".join(s["id"] for s in sources[:20])

    @tool
    def build_query() -> str:
        """Build an optimized NewsAPI search query from the claim.

        Removes stop words and truncates to 100 characters at a word boundary.
        """
        return build_search_query(input["normalized_claim"])

    @tool
    async def search_news(query: str) -> str:
        """Search NewsAPI for articles from this spectrum's sources.

        Args:
            query: Search query string (use the output from build_query).
        """
        api_key = os.environ.get("NEWSAPI_KEY", "")
        if not api_key:
            logger.warning("NEWSAPI_KEY not configured for coverage-%s", spectrum)
            return "Error: NEWSAPI_KEY not configured."

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
                if resp.status_code >= 400:
                    return f"Error: HTTP {resp.status_code}"
                articles = resp.json().get("articles", [])
        except Exception as exc:
            logger.warning("NewsAPI error for coverage-%s: %s", spectrum, exc)
            return f"Error: {exc}"

        results.articles = articles

        if not articles:
            return "No articles found from these sources."

        lines = []
        for a in articles[:5]:
            title = a.get("title", "No title")
            src = a.get("source", {}).get("name", "Unknown")
            lines.append(f"- {title} ({src})")
        return f"Found {len(articles)} article(s):\n" + "\n".join(lines)

    @tool
    def detect_framing() -> str:
        """Analyze headline sentiment and classify framing of found articles.

        Must be called after search_news. Classifies framing as SUPPORTIVE,
        CRITICAL, NEUTRAL, or ABSENT based on VADER-style sentiment scoring.
        """
        if not results.articles:
            results.framing_cwe = "ABSENT^Not Covered^FCK"
            results.compound_score = 0.0
            return "No articles to analyze. Framing: ABSENT"

        headlines = [a.get("title", "") for a in results.articles[:5] if a.get("title")]
        compound = compute_compound_sentiment(headlines)
        framing_cwe = classify_framing(compound)

        results.framing_cwe = framing_cwe
        results.compound_score = compound

        label = framing_cwe.split("^")[0]
        return f"Framing: {label} (compound sentiment: {compound:.2f})"

    @tool
    def find_top_source() -> str:
        """Find the highest-credibility source among found articles.

        Must be called after search_news. Ranks articles by source
        credibility and returns the top match.
        """
        if not results.articles:
            results.top_source = None
            return "No articles to select from."

        top = select_top_source(results.articles, sources)
        if top:
            name, url = top
            results.top_source = {"name": name, "url": url}
            return f"Top source: {name} ({url})"

        results.top_source = None
        return "No matching source found in credibility rankings."

    return [build_query, search_news, detect_framing, find_top_source]


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


def create_agent(
    spectrum: str,
    sources: list[dict],
    input: CoverageInput,
    results: _Results,
):
    """Build a compiled ReAct agent graph for spectrum-specific coverage analysis.

    The factory creates an agent parameterized by media *spectrum*
    (left/center/right) and *sources* (NewsAPI source list).  Tools
    close over *input* for claim context and *results* to accumulate
    structured output.

    The returned graph accepts ``{"messages": [HumanMessage(...)]}``
    and runs the LLM tool-calling loop until the agent decides to stop.

    Args:
        spectrum: Media spectrum -- ``"left"``, ``"center"``, or ``"right"``.
        sources: List of source dicts with ``id``, ``name``, and
            ``credibility_rank`` keys.
        input: Pre-extracted claim context from PipelineState.
        results: Accumulator written to by tools during invocation.

    Returns:
        Compiled LangGraph agent.
    """
    prompt = _SYSTEM_PROMPT.format(spectrum=spectrum)
    tools = _build_tools(spectrum, sources, input, results)
    model = ChatAnthropic(model=MODEL_ID, max_tokens=1024)
    return create_react_agent(model, tools, prompt=prompt)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run_coverage_agent(
    spectrum: str,
    sources: list[dict],
    input: CoverageInput,
    ctx: PipelineContext,
) -> CoverageOutput:
    """Run the coverage agent: LLM-driven ReAct loop over 4 coverage tools.

    Args:
        spectrum: Media spectrum -- ``"left"``, ``"center"``, or ``"right"``.
        sources: Source list with ``id``, ``name``, ``credibility_rank`` keys.
        input: Pre-extracted claim context from PipelineState.
        ctx: PipelineContext for observation publishing and heartbeats.

    Returns:
        CoverageOutput with articles, framing, compound_score, and top_source.
    """
    agent_name = f"coverage-{spectrum}"
    ctx.heartbeat(agent_name)
    await ctx.publish_progress(agent_name, f"Analyzing {spectrum}-spectrum coverage...")

    results = _Results()
    agent = create_agent(spectrum, sources, input, results)

    claim_msg = f"Analyze news coverage for this claim:\n\nClaim: {input['normalized_claim']}"

    await agent.ainvoke({"messages": [HumanMessage(content=claim_msg)]})
    ctx.heartbeat(agent_name)

    # Publish observations from accumulated results
    await _publish_observations(results, ctx, agent_name)

    # Build article list with framing metadata
    coverage_articles = []
    framing_label = results.framing_cwe.split("^")[0]
    for article in results.articles:
        coverage_articles.append(
            {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "source": article.get("source", {}).get("name", ""),
                "framing": framing_label,
            }
        )

    article_count = len(coverage_articles)
    if results.top_source:
        desc = f"{article_count} article(s), top={results.top_source['name']}"
    else:
        desc = f"{article_count} article(s)"
    await ctx.publish_progress(
        agent_name,
        f"Coverage complete: {desc}, framing={framing_label}",
    )

    return CoverageOutput(
        articles=coverage_articles,
        framing=framing_label,
        compound_score=results.compound_score,
        top_source=results.top_source,
    )


# ---------------------------------------------------------------------------
# Observation publishing helpers
# ---------------------------------------------------------------------------


async def _publish_observations(
    results: _Results,
    ctx: PipelineContext,
    agent_name: str,
) -> None:
    """Publish COVERAGE_* observations from accumulated results."""
    # Article count
    await ctx.publish_observation(
        agent=agent_name,
        code=ObservationCode.COVERAGE_ARTICLE_COUNT,
        value=str(len(results.articles)),
        value_type=ValueType.NM,
        method="search_newsapi",
        units="count",
    )

    # Framing
    await ctx.publish_observation(
        agent=agent_name,
        code=ObservationCode.COVERAGE_FRAMING,
        value=results.framing_cwe,
        value_type=ValueType.CWE,
        method="detect_framing",
    )

    # Top source
    if results.top_source:
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_TOP_SOURCE,
            value=results.top_source["name"],
            value_type=ValueType.ST,
            method="select_top_source",
        )
        await ctx.publish_observation(
            agent=agent_name,
            code=ObservationCode.COVERAGE_TOP_SOURCE_URL,
            value=results.top_source["url"],
            value_type=ValueType.ST,
            method="select_top_source",
        )
