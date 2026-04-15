"""Synthesizer agent -- LangGraph StateGraph (resolve → score → map → narrate).

The synthesizer is the terminal agent in the claim verification pipeline.
Unlike other agents that use create_react_agent (LLM-driven tool selection),
the synthesizer uses a fixed-sequence StateGraph because its 4 steps always
execute in the same order with deterministic routing.

The agent graph receives upstream observations and produces a typed verdict
with confidence score, narrative, and observation summary. Infrastructure
concerns (observation publishing to Redis for SSE relay) are handled via
PipelineContext passed through LangGraph's RunnableConfig.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from swarm_reasoning.agents.synthesizer.mapper import VerdictMapper
from swarm_reasoning.agents.synthesizer.models import (
    ResolvedObservationSet,
    SynthesizerInput,
    SynthesizerOutput,
)
from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator
from swarm_reasoning.agents.synthesizer.resolver import resolve_from_state
from swarm_reasoning.agents.synthesizer.scorer import ConfidenceScorer
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context

logger = logging.getLogger(__name__)

AGENT_NAME = "synthesizer"


# ---------------------------------------------------------------------------
# Internal state for the synthesizer StateGraph
# ---------------------------------------------------------------------------


class SynthesizerGraphState(TypedDict, total=False):
    """Internal state threaded through the synthesizer StateGraph.

    Input fields are populated by the pipeline node wrapper before invocation.
    Working fields are populated sequentially by each graph node.
    """

    # Input (provided at graph invocation)
    observations: list[dict]

    # After resolve node
    resolved: Any  # ResolvedObservationSet (dataclass, not JSON-serializable)

    # After score node
    confidence_score: float | None

    # After map node
    verdict_code: str
    verdict_cwe: str
    override_reason: str

    # After narrate node
    narrative: str

    # Accumulated output
    verdict_observations: list[dict]


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def resolve_node(state: SynthesizerGraphState, config: RunnableConfig) -> dict:
    """Resolve upstream observations using epistemic status precedence.

    Applies C > F precedence per (agent, code) pair. Publishes
    SYNTHESIS_SIGNAL_COUNT observation for SSE relay.
    """
    ctx = _get_ctx(config)

    resolved = resolve_from_state(state.get("observations", []))
    logger.info(
        "resolve_node: resolved %d signals (%d excluded, %d warnings)",
        resolved.synthesis_signal_count,
        len(resolved.excluded_observations),
        len(resolved.warnings),
    )

    if ctx is not None:
        await ctx.publish_progress(AGENT_NAME, "Resolving observations...")
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.SYNTHESIS_SIGNAL_COUNT,
            value=str(resolved.synthesis_signal_count),
            value_type=ValueType.NM,
            units="count",
            method="resolve_observations",
        )

    return {"resolved": resolved}


async def score_node(state: SynthesizerGraphState, config: RunnableConfig) -> dict:
    """Compute calibrated confidence score from resolved observations.

    Returns None when synthesis_signal_count < 5 (UNVERIFIABLE).
    Publishes CONFIDENCE_SCORE observation when score is not None.
    """
    ctx = _get_ctx(config)
    resolved: ResolvedObservationSet = state["resolved"]

    scorer = ConfidenceScorer()
    confidence_score = scorer.compute(resolved)

    if ctx is not None and confidence_score is not None:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CONFIDENCE_SCORE,
            value=f"{confidence_score:.4f}",
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
            method="compute_confidence",
        )

    return {"confidence_score": confidence_score}


async def map_node(state: SynthesizerGraphState, config: RunnableConfig) -> dict:
    """Map confidence score to verdict with ClaimReview override logic.

    Publishes VERDICT and optionally SYNTHESIS_OVERRIDE_REASON observations.
    """
    ctx = _get_ctx(config)
    resolved: ResolvedObservationSet = state["resolved"]

    mapper = VerdictMapper()
    verdict_code, verdict_cwe, override_reason = mapper.map_verdict(
        state.get("confidence_score"), resolved
    )

    if ctx is not None:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.VERDICT,
            value=verdict_cwe,
            value_type=ValueType.CWE,
            method="map_verdict",
        )
        if override_reason:
            await ctx.publish_observation(
                agent=AGENT_NAME,
                code=ObservationCode.SYNTHESIS_OVERRIDE_REASON,
                value=override_reason,
                value_type=ValueType.ST,
                method="map_verdict",
            )

    return {
        "verdict_code": verdict_code,
        "verdict_cwe": verdict_cwe,
        "override_reason": override_reason,
    }


async def narrate_node(state: SynthesizerGraphState, config: RunnableConfig) -> dict:
    """Generate human-readable verdict narrative via LLM with fallback.

    Publishes VERDICT_NARRATIVE observation and builds the final
    verdict_observations summary list.
    """
    ctx = _get_ctx(config)
    resolved: ResolvedObservationSet = state["resolved"]
    confidence_score = state.get("confidence_score")
    verdict_code = state["verdict_code"]
    verdict_cwe = state["verdict_cwe"]
    override_reason = state.get("override_reason", "")

    generator = NarrativeGenerator()
    narrative = await generator.generate(
        resolved=resolved,
        verdict=verdict_code,
        confidence_score=confidence_score,
        override_reason=override_reason,
        warnings=resolved.warnings,
        signal_count=resolved.synthesis_signal_count,
    )

    if ctx is not None:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.VERDICT_NARRATIVE,
            value=narrative,
            value_type=ValueType.TX,
            method="generate_narrative",
        )

    verdict_observations = _build_verdict_observations(
        resolved, confidence_score, verdict_code, verdict_cwe, override_reason, narrative
    )

    return {
        "narrative": narrative,
        "verdict_observations": verdict_observations,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_ctx(config: RunnableConfig) -> PipelineContext | None:
    """Extract PipelineContext from config, returning None if absent."""
    try:
        return get_pipeline_context(config)
    except (KeyError, TypeError):
        return None


def _build_verdict_observations(
    resolved: ResolvedObservationSet,
    confidence_score: float | None,
    verdict_code: str,
    verdict_cwe: str,
    override_reason: str,
    narrative: str,
) -> list[dict]:
    """Build the list of observation dicts produced by the synthesizer."""
    obs: list[dict] = [
        {
            "agent": AGENT_NAME,
            "code": "SYNTHESIS_SIGNAL_COUNT",
            "value": str(resolved.synthesis_signal_count),
            "value_type": "NM",
        },
        {
            "agent": AGENT_NAME,
            "code": "VERDICT",
            "value": verdict_cwe,
            "value_type": "CWE",
        },
        {
            "agent": AGENT_NAME,
            "code": "VERDICT_NARRATIVE",
            "value": narrative,
            "value_type": "TX",
        },
    ]
    if confidence_score is not None:
        obs.append(
            {
                "agent": AGENT_NAME,
                "code": "CONFIDENCE_SCORE",
                "value": f"{confidence_score:.4f}",
                "value_type": "NM",
            }
        )
    if override_reason:
        obs.append(
            {
                "agent": AGENT_NAME,
                "code": "SYNTHESIS_OVERRIDE_REASON",
                "value": override_reason,
                "value_type": "ST",
            }
        )
    return obs


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_synthesizer_graph() -> StateGraph:
    """Build the synthesizer StateGraph: resolve → score → map → narrate.

    Returns a compiled graph that accepts ``SynthesizerGraphState`` input
    (minimally ``{"observations": [...]}``).
    """
    builder = StateGraph(SynthesizerGraphState)

    builder.add_node("resolve", resolve_node)
    builder.add_node("score", score_node)
    builder.add_node("map", map_node)
    builder.add_node("narrate", narrate_node)

    builder.set_entry_point("resolve")
    builder.add_edge("resolve", "score")
    builder.add_edge("score", "map")
    builder.add_edge("map", "narrate")
    builder.add_edge("narrate", END)

    return builder.compile()


# Module-level compiled graph
synthesizer_graph = build_synthesizer_graph()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run_synthesizer(
    input: SynthesizerInput,
    ctx: PipelineContext,
) -> SynthesizerOutput:
    """Run the synthesizer agent: resolve → score → map → narrate.

    Args:
        input: Upstream observations from the pipeline.
        ctx: PipelineContext for observation publishing and heartbeats.

    Returns:
        SynthesizerOutput with verdict, confidence, narrative,
        verdict_observations, and override_reason.
    """
    ctx.heartbeat(AGENT_NAME)
    await ctx.publish_progress(AGENT_NAME, "Beginning verdict synthesis")

    config: RunnableConfig = {"configurable": {"pipeline_context": ctx}}

    result = await synthesizer_graph.ainvoke(dict(input), config=config)

    conf_score = result.get("confidence_score")
    verdict_code = result.get("verdict_code", "UNVERIFIABLE")
    conf_str = f"{conf_score:.4f}" if conf_score is not None else "unverifiable"
    await ctx.publish_progress(AGENT_NAME, f"Verdict: {verdict_code} (confidence: {conf_str})")

    return SynthesizerOutput(
        verdict=verdict_code,
        confidence=conf_score,
        narrative=result.get("narrative", ""),
        verdict_observations=result.get("verdict_observations", []),
        override_reason=result.get("override_reason", ""),
    )
