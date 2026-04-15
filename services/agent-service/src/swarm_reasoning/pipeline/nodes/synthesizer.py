"""Synthesizer pipeline node -- verdict synthesis via agent StateGraph (M5.1).

Terminal node in the LangGraph pipeline. Translates PipelineState into
SynthesizerInput, invokes the synthesizer agent graph (resolve → score →
map → narrate), and maps the result back to PipelineState updates.

The not-check-worthy bypass is handled here in the pipeline wrapper,
not in the agent graph, because it skips synthesis entirely.

Data source: PipelineState (not Redis Streams).
Side-effects: observations published to Redis via PipelineContext for SSE relay.
"""

from __future__ import annotations

import logging

from langchain_core.runnables import RunnableConfig

from swarm_reasoning.agents.synthesizer.agent import synthesizer_graph
from swarm_reasoning.agents.synthesizer.models import SynthesizerInput
from swarm_reasoning.agents.synthesizer.resolver import resolve_from_state
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

AGENT_NAME = "synthesizer"


# ---------------------------------------------------------------------------
# Not-check-worthy bypass
# ---------------------------------------------------------------------------


async def _not_check_worthy_bypass(
    state: PipelineState, ctx: PipelineContext
) -> dict:
    """Produce a NOT_CHECK_WORTHY verdict without observation resolution."""
    logger.info("synthesizer_node: not-check-worthy bypass")
    await ctx.publish_progress(AGENT_NAME, "Claim not check-worthy, producing bypass verdict")

    verdict = "NOT_CHECK_WORTHY"
    confidence = 1.0
    score_text = state.get("check_worthy_score", "N/A")
    narrative = (
        f"This claim was determined to not be check-worthy "
        f"(check-worthiness score: {score_text}). "
        f"The claim does not contain a verifiable factual assertion that warrants "
        f"fact-checking analysis. Claims that are not check-worthy include opinions, "
        f"predictions, subjective statements, and other assertions that cannot be "
        f"verified against objective evidence."
    )

    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.VERDICT,
        value="NOT_CHECK_WORTHY^Not Check-Worthy^POLITIFACT",
        value_type=ValueType.CWE,
        method="synthesizer_node_bypass",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CONFIDENCE_SCORE,
        value="1.0000",
        value_type=ValueType.NM,
        units="score",
        reference_range="0.0-1.0",
        method="synthesizer_node_bypass",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.VERDICT_NARRATIVE,
        value=narrative,
        value_type=ValueType.TX,
        method="synthesizer_node_bypass",
    )

    await ctx.publish_progress(AGENT_NAME, f"Verdict: {verdict}")

    return {
        "verdict": verdict,
        "confidence": confidence,
        "narrative": narrative,
        "verdict_observations": [],
    }


# ---------------------------------------------------------------------------
# Pipeline node
# ---------------------------------------------------------------------------


async def synthesizer_node(state: PipelineState, config: RunnableConfig) -> dict:
    """Pipeline node: verdict synthesis via synthesizer agent graph.

    Translates PipelineState → SynthesizerInput, invokes the agent
    StateGraph, and maps the output back to PipelineState updates.

    The not-check-worthy bypass is handled directly by this wrapper
    since it skips the agent graph entirely.

    Returns dict with: verdict, confidence, narrative, verdict_observations.
    """
    try:
        ctx = get_pipeline_context(config)
    except KeyError:
        logger.info("synthesizer_node: no PipelineContext in config (placeholder mode)")
        return {}
    ctx.heartbeat("synthesizer")
    await ctx.publish_progress(AGENT_NAME, "Beginning verdict synthesis")

    # Not-check-worthy bypass
    if not state.get("is_check_worthy", True):
        return await _not_check_worthy_bypass(state, ctx)

    # Translate PipelineState → SynthesizerInput
    synth_input: SynthesizerInput = {
        "observations": state.get("observations", []),
    }

    # Invoke the synthesizer agent graph
    result = await synthesizer_graph.ainvoke(synth_input, config=config)

    # Map agent output → PipelineState update
    conf_score = result.get("confidence_score")
    verdict_code = result.get("verdict_code", "UNVERIFIABLE")
    conf_str = f"{conf_score:.4f}" if conf_score is not None else "unverifiable"
    await ctx.publish_progress(
        AGENT_NAME, f"Verdict: {verdict_code} (confidence: {conf_str})"
    )

    return {
        "verdict": verdict_code,
        "confidence": conf_score,
        "narrative": result.get("narrative", ""),
        "verdict_observations": result.get("verdict_observations", []),
    }
