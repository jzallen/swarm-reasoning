"""Evidence agent -- LLM-driven ReAct loop for evidence gathering.

Uses create_react_agent from LangGraph to let the LLM dynamically select
and sequence evidence-gathering tools.  Unlike the synthesizer (fixed
StateGraph) and validation agent (procedural chain), the evidence agent
uses LLM reasoning to decide which sources to search, how many to try,
and how to interpret intermediate results.

Four tools:

1. ``search_factchecks`` -- Google Fact Check Tools API lookup
2. ``lookup_domain_sources`` -- domain → authoritative-source routing
3. ``fetch_source_content`` -- HTTP content retrieval
4. ``score_evidence`` -- alignment scoring and confidence computation

Accepts EvidenceInput + PipelineContext, returns EvidenceOutput.
Publishes CLAIMREVIEW_* and DOMAIN_* observations via PipelineContext.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from swarm_reasoning.agents.evidence.models import EvidenceInput, EvidenceOutput
from swarm_reasoning.agents.evidence.tools import (
    compute_evidence_confidence,
    derive_search_query,
    format_source_url,
    score_claim_alignment,
)
from swarm_reasoning.agents.evidence.tools import (
    fetch_source_content as _fetch_source_content,
)
from swarm_reasoning.agents.evidence.tools import (
    lookup_domain_sources as _lookup_domain_sources,
)
from swarm_reasoning.agents.evidence.tools import (
    search_factchecks as _search_factchecks,
)
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

AGENT_NAME = "evidence"
MODEL_ID = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "You are an evidence-gathering agent in a fact-checking pipeline. "
    "Gather evidence for or against the given claim using your tools.\n\n"
    "Workflow:\n"
    "1. Search for existing fact-checks with search_factchecks\n"
    "2. Look up domain-authoritative sources with lookup_domain_sources\n"
    "3. Fetch content from the top source with fetch_source_content\n"
    "4. Score the fetched content with score_evidence\n\n"
    "Always start with the fact-check lookup.  Then proceed to domain "
    "sources.  Try up to 3 domain source URLs if the first returns an "
    "error.  Stop after scoring evidence from one successful source."
)


# ---------------------------------------------------------------------------
# Result accumulator -- tools write to this via closure
# ---------------------------------------------------------------------------


@dataclass
class _Results:
    """Accumulates structured results from tool invocations."""

    claimreview_matches: list[dict] = field(default_factory=list)
    domain_sources: list[dict] = field(default_factory=list)
    best_confidence: float = 0.0


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def _build_tools(input: EvidenceInput, results: _Results) -> list:
    """Build LangChain tools scoped to the given evidence input.

    Tools close over *input* for claim context and *results* to accumulate
    structured output that ``run_evidence_agent`` converts to
    ``EvidenceOutput``.
    """

    @tool
    async def search_factchecks() -> str:
        """Search Google Fact Check Tools API for existing reviews of the claim."""
        result = await _search_factchecks(
            claim=input["normalized_claim"],
            persons=input.get("persons"),
            organizations=input.get("organizations"),
        )
        if result.error:
            return f"Error: {result.error}"
        if not result.matched:
            return "No matching fact-checks found."

        match = {
            "source": result.source,
            "rating": result.rating,
            "url": result.url,
            "score": round(result.score, 2),
        }
        results.claimreview_matches.append(match)
        return (
            f"Match found (score: {result.score:.2f}):\n"
            f"  Rating: {result.rating}\n"
            f"  Source: {result.source}\n"
            f"  URL: {result.url}"
        )

    @tool
    def lookup_domain_sources() -> str:
        """Look up authoritative sources for the claim's domain.

        Returns a JSON list of sources with name and pre-formatted URL.
        """
        domain = input.get("claim_domain", "OTHER")
        sources = _lookup_domain_sources(domain)
        search_query = derive_search_query(
            input["normalized_claim"],
            input.get("persons"),
            input.get("organizations"),
        )
        return json.dumps(
            [
                {"name": s.name, "url": format_source_url(s.url_template, search_query)}
                for s in sources
            ]
        )

    @tool
    async def fetch_source_content(url: str) -> str:
        """Fetch text content from a source URL.

        Args:
            url: The full URL to fetch (use URLs from lookup_domain_sources).
        """
        result = await _fetch_source_content(url)
        if result.error:
            return f"Error fetching {url}: {result.error}"
        return result.content

    @tool
    def score_evidence(content: str, source_name: str, source_url: str) -> str:
        """Score how well fetched content aligns with the claim.

        Args:
            content: The fetched source content to evaluate.
            source_name: Name of the source (e.g. CDC, WHO).
            source_url: URL the content was fetched from.
        """
        alignment_result = score_claim_alignment(content, input["normalized_claim"])
        confidence = compute_evidence_confidence(alignment_result.alignment)

        results.domain_sources.append(
            {
                "name": source_name,
                "url": source_url,
                "alignment": alignment_result.alignment.value,
                "confidence": confidence,
            }
        )
        if confidence > results.best_confidence:
            results.best_confidence = confidence

        return (
            f"Alignment: {alignment_result.alignment.value} "
            f"({alignment_result.description})\n"
            f"Confidence: {confidence:.2f}"
        )

    return [search_factchecks, lookup_domain_sources, fetch_source_content, score_evidence]


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


def build_evidence_agent(
    input: EvidenceInput,
    results: _Results,
) -> create_react_agent:
    """Build a compiled ReAct agent graph for evidence gathering.

    The returned graph accepts ``{"messages": [HumanMessage(...)]}`` and
    runs the LLM tool-calling loop until the agent decides to stop.
    """
    tools = _build_tools(input, results)
    model = ChatAnthropic(model=MODEL_ID, max_tokens=1024)
    return create_react_agent(model, tools, prompt=SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run_evidence_agent(
    input: EvidenceInput,
    ctx: PipelineContext,
) -> EvidenceOutput:
    """Run the evidence agent: LLM-driven ReAct loop over 4 evidence tools.

    Args:
        input: Pre-extracted claim context from PipelineState.
        ctx: PipelineContext for observation publishing and heartbeats.

    Returns:
        EvidenceOutput with claimreview_matches, domain_sources,
        and evidence_confidence.
    """
    ctx.heartbeat(AGENT_NAME)
    await ctx.publish_progress(AGENT_NAME, "Gathering evidence...")

    results = _Results()
    agent = build_evidence_agent(input, results)

    claim_msg = (
        f"Gather evidence for this claim:\n\n"
        f"Claim: {input['normalized_claim']}\n"
        f"Domain: {input.get('claim_domain', 'OTHER')}\n"
        f"Persons: {', '.join(input.get('persons', []) or [])}\n"
        f"Organizations: {', '.join(input.get('organizations', []) or [])}"
    )

    await agent.ainvoke({"messages": [HumanMessage(content=claim_msg)]})
    ctx.heartbeat(AGENT_NAME)

    # Publish observations from accumulated results
    await _publish_claimreview_observations(results, ctx)
    await _publish_domain_observations(results, ctx)

    match_desc = (
        f"found {len(results.claimreview_matches)} match(es)"
        if results.claimreview_matches
        else "no matches"
    )
    source_name = results.domain_sources[0]["name"] if results.domain_sources else "N/A"
    alignment = results.domain_sources[0]["alignment"] if results.domain_sources else "ABSENT"
    await ctx.publish_progress(
        AGENT_NAME,
        f"Evidence complete: ClaimReview {match_desc}, "
        f"domain source={source_name}, alignment={alignment}",
    )

    return EvidenceOutput(
        claimreview_matches=results.claimreview_matches,
        domain_sources=results.domain_sources,
        evidence_confidence=results.best_confidence,
    )


# ---------------------------------------------------------------------------
# Observation publishing helpers
# ---------------------------------------------------------------------------


async def _publish_claimreview_observations(results: _Results, ctx: PipelineContext) -> None:
    """Publish CLAIMREVIEW_* observations from accumulated results."""
    if results.claimreview_matches:
        match = results.claimreview_matches[0]
        system = match["source"].upper().replace(" ", "_")
        rating_code = match["rating"].upper().replace(" ", "_")

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
            value=f"{rating_code}^{match['rating']}^{system}",
            value_type=ValueType.CWE,
            method="lookup_claimreview",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CLAIMREVIEW_SOURCE,
            value=match["source"],
            value_type=ValueType.ST,
            method="lookup_claimreview",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CLAIMREVIEW_URL,
            value=match.get("url") or "N/A",
            value_type=ValueType.ST,
            method="lookup_claimreview",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CLAIMREVIEW_MATCH_SCORE,
            value=f"{match['score']:.2f}",
            value_type=ValueType.NM,
            method="compute_similarity",
            units="score",
            reference_range="0.0-1.0",
        )
    else:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CLAIMREVIEW_MATCH,
            value="FALSE^No Match^FCK",
            value_type=ValueType.CWE,
            method="lookup_claimreview",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CLAIMREVIEW_MATCH_SCORE,
            value="0.0",
            value_type=ValueType.NM,
            method="compute_similarity",
            units="score",
            reference_range="0.0-1.0",
        )


async def _publish_domain_observations(results: _Results, ctx: PipelineContext) -> None:
    """Publish DOMAIN_* observations from accumulated results."""
    if results.domain_sources:
        source = results.domain_sources[0]
        alignment = source["alignment"]
        alignment_desc = alignment.replace("_", " ").title()

        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_SOURCE_NAME,
            value=source["name"],
            value_type=ValueType.ST,
            method="lookup_domain_sources",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_SOURCE_URL,
            value=source["url"],
            value_type=ValueType.ST,
            method="lookup_domain_sources",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT,
            value=f"{alignment}^{alignment_desc}^FCK",
            value_type=ValueType.CWE,
            method="score_claim_alignment",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_CONFIDENCE,
            value=f"{source['confidence']:.2f}",
            value_type=ValueType.NM,
            method="compute_evidence_confidence",
            units="score",
            reference_range="0.0-1.0",
        )
    else:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_SOURCE_NAME,
            value="N/A",
            value_type=ValueType.ST,
            method="lookup_domain_sources",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_SOURCE_URL,
            value="N/A",
            value_type=ValueType.ST,
            method="lookup_domain_sources",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT,
            value="ABSENT^No Evidence Found^FCK",
            value_type=ValueType.CWE,
            method="score_claim_alignment",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_CONFIDENCE,
            value="0.00",
            value_type=ValueType.NM,
            method="compute_evidence_confidence",
            units="score",
            reference_range="0.0-1.0",
        )
