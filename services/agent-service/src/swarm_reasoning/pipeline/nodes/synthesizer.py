"""Synthesizer pipeline node -- verdict synthesis with 4 tools (M5.1).

Terminal node in the LangGraph pipeline. Reads upstream observations from
PipelineState, resolves epistemic conflicts, computes a weighted confidence
score, maps to a PolitiFact verdict, and generates a human-readable narrative.

Data source: PipelineState (not Redis Streams).
Side-effects: observations published to Redis via PipelineContext for SSE relay.

Tools (executed in fixed order):
    1. resolve_observations -- epistemic resolution of upstream observations
    2. compute_confidence   -- deterministic weighted scoring
    3. map_verdict          -- threshold mapping with ClaimReview override
    4. generate_narrative   -- LLM-powered narrative with template fallback
"""

from __future__ import annotations

import logging

from langchain_core.runnables import RunnableConfig

from swarm_reasoning.agents.synthesizer.mapper import VerdictMapper
from swarm_reasoning.agents.synthesizer.models import (
    ResolvedObservation,
    ResolvedObservationSet,
)
from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator
from swarm_reasoning.agents.synthesizer.scorer import ConfidenceScorer
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

AGENT_NAME = "synthesizer"


# ---------------------------------------------------------------------------
# Observation resolution from PipelineState
# ---------------------------------------------------------------------------


def _to_resolved(obs: dict, resolution_method: str) -> ResolvedObservation:
    """Convert a state observation dict to a ResolvedObservation."""
    code = obs.get("code", "")
    if hasattr(code, "value"):
        code = code.value
    vt = obs.get("value_type", obs.get("valueType", ""))
    if hasattr(vt, "value"):
        vt = vt.value
    return ResolvedObservation(
        agent=obs.get("agent", ""),
        code=code,
        value=obs.get("value", ""),
        value_type=vt,
        seq=obs.get("seq", 0),
        status=obs.get("status", "F"),
        resolution_method=resolution_method,
        timestamp=obs.get("timestamp", ""),
        method=obs.get("method"),
        note=obs.get("note"),
        units=obs.get("units"),
        reference_range=obs.get("reference_range", obs.get("referenceRange")),
    )


def resolve_from_state(observations: list[dict]) -> ResolvedObservationSet:
    """Resolve observations from PipelineState using epistemic status precedence.

    Same algorithm as ``ObservationResolver`` but reads from the state
    ``observations`` list instead of Redis Streams.

    For each (agent, code) pair:
      1. If any C-status observation exists, use highest-seq C → LATEST_C
      2. Else if any F-status, use highest-seq F → LATEST_F
      3. X-status excluded silently; P-status excluded with warning.
    """
    pair_observations: dict[tuple[str, str], list[dict]] = {}
    excluded: list[dict] = []
    warnings_list: list[str] = []

    for obs in observations:
        agent = obs.get("agent", "")
        code = obs.get("code", "")
        if not agent or not code:
            continue

        if hasattr(code, "value"):
            code = code.value

        key = (agent, code)
        if key not in pair_observations:
            pair_observations[key] = []
        pair_observations[key].append(obs)

    resolved: list[ResolvedObservation] = []

    for (agent_name, code), obs_list in pair_observations.items():
        c_status = [o for o in obs_list if o.get("status") == "C"]
        f_status = [o for o in obs_list if o.get("status") == "F"]
        x_status = [o for o in obs_list if o.get("status") == "X"]
        p_status = [o for o in obs_list if o.get("status") == "P"]

        if c_status:
            winner = max(c_status, key=lambda o: o.get("seq", 0))
            resolved.append(_to_resolved(winner, "LATEST_C"))
        elif f_status:
            winner = max(f_status, key=lambda o: o.get("seq", 0))
            resolved.append(_to_resolved(winner, "LATEST_F"))
        else:
            for o in x_status:
                excluded.append(o)
            for o in p_status:
                excluded.append(o)
                warnings_list.append(
                    f"WARNING: {agent_name}:{code} has only P-status observations; "
                    "upstream agent may not have finalized."
                )

    return ResolvedObservationSet(
        observations=resolved,
        synthesis_signal_count=len(resolved),
        excluded_observations=excluded,
        warnings=warnings_list,
    )


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
# Node function
# ---------------------------------------------------------------------------


async def synthesizer_node(state: PipelineState, config: RunnableConfig) -> dict:
    """Pipeline node: verdict synthesis (M5.1).

    Terminal node that resolves upstream observations, computes confidence,
    maps a verdict, and generates a narrative. All upstream data comes from
    PipelineState; observations are published to Redis for SSE relay.

    Tools executed in fixed order:
        1. resolve_observations → ResolvedObservationSet
        2. compute_confidence   → float | None
        3. map_verdict          → (verdict_code, verdict_cwe, override_reason)
        4. generate_narrative   → narrative text

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

    # --- Tool 1: Resolve observations from PipelineState ---
    resolved = resolve_from_state(state.get("observations", []))
    logger.info(
        "synthesizer_node: resolved %d signals (%d excluded, %d warnings)",
        resolved.synthesis_signal_count,
        len(resolved.excluded_observations),
        len(resolved.warnings),
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.SYNTHESIS_SIGNAL_COUNT,
        value=str(resolved.synthesis_signal_count),
        value_type=ValueType.NM,
        units="count",
        method="resolve_observations",
    )

    # --- Tool 2: Compute confidence ---
    scorer = ConfidenceScorer()
    confidence_score = scorer.compute(resolved)
    if confidence_score is not None:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CONFIDENCE_SCORE,
            value=f"{confidence_score:.4f}",
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
            method="compute_confidence",
        )

    # --- Tool 3: Map verdict ---
    mapper = VerdictMapper()
    verdict_code, verdict_cwe, override_reason = mapper.map_verdict(
        confidence_score, resolved
    )
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

    # --- Tool 4: Generate narrative (LLM-powered with fallback) ---
    generator = NarrativeGenerator()
    narrative = await generator.generate(
        resolved=resolved,
        verdict=verdict_code,
        confidence_score=confidence_score,
        override_reason=override_reason,
        warnings=resolved.warnings,
        signal_count=resolved.synthesis_signal_count,
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.VERDICT_NARRATIVE,
        value=narrative,
        value_type=ValueType.TX,
        method="generate_narrative",
    )

    # Build verdict observations summary
    verdict_observations = _build_verdict_observations(
        resolved, confidence_score, verdict_code, verdict_cwe, override_reason, narrative
    )

    conf_str = f"{confidence_score:.4f}" if confidence_score is not None else "unverifiable"
    await ctx.publish_progress(
        AGENT_NAME, f"Verdict: {verdict_code} (confidence: {conf_str})"
    )

    return {
        "verdict": verdict_code,
        "confidence": confidence_score,
        "narrative": narrative,
        "verdict_observations": verdict_observations,
    }


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
        obs.append({
            "agent": AGENT_NAME,
            "code": "CONFIDENCE_SCORE",
            "value": f"{confidence_score:.4f}",
            "value_type": "NM",
        })
    if override_reason:
        obs.append({
            "agent": AGENT_NAME,
            "code": "SYNTHESIS_OVERRIDE_REASON",
            "value": override_reason,
            "value_type": "ST",
        })
    return obs
