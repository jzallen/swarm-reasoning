"""Synthesizer pipeline node -- thin wrapper delegating to agents/synthesizer.

Translates PipelineState -> SynthesizerInput, invokes the synthesizer agent
graph (resolve -> score -> map -> narrate), and translates SynthesizerOutput
-> PipelineState updates.  Contains no domain logic; all observation
resolution, scoring, verdict mapping, and narration live in the agent module.

The not-check-worthy bypass is handled here in the pipeline wrapper,
not in the agent graph, because it skips synthesis entirely.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from swarm_reasoning.agents.synthesizer import (
    SynthesizerInput,
    SynthesizerOutput,
    run_synthesizer,
)
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

AGENT_NAME = "synthesizer"


# ---------------------------------------------------------------------------
# PipelineState <-> SynthesizerInput/Output translation
# ---------------------------------------------------------------------------


def _extract_input(state: PipelineState) -> SynthesizerInput:
    """Extract SynthesizerInput from PipelineState."""
    return SynthesizerInput(
        observations=state.get("observations", []),
    )


def _apply_output(output: SynthesizerOutput) -> dict[str, Any]:
    """Translate SynthesizerOutput to PipelineState update dict."""
    return {
        "verdict": output["verdict"],
        "confidence": output["confidence"],
        "narrative": output["narrative"],
        "verdict_observations": output["verdict_observations"],
    }


# ---------------------------------------------------------------------------
# Not-check-worthy bypass
# ---------------------------------------------------------------------------


async def _not_check_worthy_bypass(state: PipelineState, ctx: PipelineContext) -> dict[str, Any]:
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


async def synthesizer_node(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Synthesizer pipeline node: delegates to the synthesizer agent graph.

    1. Handles not-check-worthy bypass (skips agent entirely)
    2. Extracts SynthesizerInput from PipelineState
    3. Invokes run_synthesizer (resolve -> score -> map -> narrate)
    4. Returns SynthesizerOutput fields as PipelineState updates
    """
    try:
        ctx = get_pipeline_context(config)
    except KeyError:
        logger.info("synthesizer_node: no PipelineContext in config (placeholder mode)")
        return {}
    ctx.heartbeat(AGENT_NAME)

    # Not-check-worthy bypass
    if not state.get("is_check_worthy", True):
        return await _not_check_worthy_bypass(state, ctx)

    synth_input = _extract_input(state)
    synth_output = await run_synthesizer(synth_input, ctx)

    return _apply_output(synth_output)
