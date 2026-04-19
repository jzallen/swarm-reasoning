"""Evidence pipeline node -- PipelineState ↔ EvidenceInput/Output translation.

Owns all PipelineContext interaction for the evidence stage:

  1. Project ``PipelineState`` into ``EvidenceInput``
  2. Invoke the evidence agent in an isolated checkpoint namespace
  3. Project the agent's final state into an ``EvidenceOutput``
  4. Publish CLAIMREVIEW_* and DOMAIN_* observations
  5. Return a state update dict for LangGraph

The agent module itself never touches PipelineContext or PipelineState,
matching the intake pattern.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import RunnableConfig

from swarm_reasoning.agents.evidence import (
    AGENT_NAME,
    EvidenceInput,
    EvidenceOutput,
    build_evidence_agent,
    initial_state_from_input,
)
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.nodes._inner_config import inner_agent_config
from swarm_reasoning.pipeline.state import PipelineState


def _extract_input(state: PipelineState) -> EvidenceInput:
    """Project PipelineState into the evidence agent's EvidenceInput contract."""
    entities: dict[str, list[str]] = state.get("entities") or {}
    selected: dict[str, Any] = state.get("selected_claim") or {}
    claim_text = selected.get("claim_text") or state.get("claim_text", "")
    return EvidenceInput(
        claim_text=claim_text,
        domain=state.get("claim_domain") or "OTHER",
        persons=list(entities.get("persons", []) or []),
        organizations=list(entities.get("organizations", []) or []),
        dates=list(entities.get("dates", []) or []),
        locations=list(entities.get("locations", []) or []),
        statistics=list(entities.get("statistics", []) or []),
    )


def _apply_output(output: EvidenceOutput) -> dict[str, Any]:
    """Translate EvidenceOutput to PipelineState update dict."""
    return {
        "claimreview_matches": output["claimreview_matches"],
        "domain_sources": output["domain_sources"],
        "evidence_confidence": output["evidence_confidence"],
    }


async def evidence_node(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Evidence pipeline node: invoke the evidence agent and publish observations.

    1. Heartbeat + opening progress event
    2. Build EvidenceInput from state and invoke the agent in an isolated
       checkpoint namespace (mirrors intake; cheap insurance against future
       interrupt-driven re-execution)
    3. Project final state to EvidenceOutput and publish CLAIMREVIEW_* /
       DOMAIN_* observations
    4. Closing progress event + state update
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat(AGENT_NAME)
    await ctx.publish_progress(AGENT_NAME, "Gathering evidence...")

    evidence_input = _extract_input(state)
    agent = build_evidence_agent()
    result = await agent.ainvoke(
        initial_state_from_input(evidence_input),
        config=inner_agent_config(config, agent=AGENT_NAME),
    )
    evidence_output: EvidenceOutput = EvidenceOutput(
        claimreview_matches=list(result.get("claimreview_matches") or []),
        domain_sources=list(result.get("domain_sources") or []),
        evidence_confidence=float(result.get("best_confidence") or 0.0),
    )

    ctx.heartbeat(AGENT_NAME)
    await _publish_claimreview_observations(evidence_output, ctx)
    await _publish_domain_observations(evidence_output, ctx)

    matches = evidence_output["claimreview_matches"]
    sources = evidence_output["domain_sources"]
    match_desc = f"found {len(matches)} match(es)" if matches else "no matches"
    source_name = sources[0]["name"] if sources else "N/A"
    alignment = sources[0]["alignment"] if sources else "ABSENT"
    await ctx.publish_progress(
        AGENT_NAME,
        f"Evidence complete: ClaimReview {match_desc}, "
        f"domain source={source_name}, alignment={alignment}",
    )

    return _apply_output(evidence_output)


# ---------------------------------------------------------------------------
# Observation publishing helpers (moved from agents/evidence/agent.py)
# ---------------------------------------------------------------------------


async def _publish_claimreview_observations(output: EvidenceOutput, ctx: PipelineContext) -> None:
    """Publish CLAIMREVIEW_* observations from the agent's structured output."""
    matches = output["claimreview_matches"]
    if matches:
        match = matches[0]
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


async def _publish_domain_observations(output: EvidenceOutput, ctx: PipelineContext) -> None:
    """Publish DOMAIN_* observations from the agent's structured output."""
    sources = output["domain_sources"]
    if sources:
        source = sources[0]
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
            method="llm_scorer_subagent",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_CONFIDENCE,
            value=f"{source['confidence']:.2f}",
            value_type=ValueType.NM,
            method="llm_scorer_subagent",
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
            method="llm_scorer_subagent",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.DOMAIN_CONFIDENCE,
            value="0.00",
            value_type=ValueType.NM,
            method="llm_scorer_subagent",
            units="score",
            reference_range="0.0-1.0",
        )
