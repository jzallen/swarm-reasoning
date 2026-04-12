"""Synthesizer Temporal activity -- Phase 3 verdict synthesis.

Final agent in the execution DAG: reads all 10 upstream agent streams,
resolves observations, computes confidence score, maps verdict,
generates narrative, and publishes 4-5 OBX observations + STOP.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from swarm_reasoning.agents.fanout_base import ClaimContext, FanoutBase
from swarm_reasoning.agents.synthesizer.mapper import VerdictMapper
from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator
from swarm_reasoning.agents.synthesizer.resolver import ObservationResolver
from swarm_reasoning.agents.synthesizer.scorer import ConfidenceScorer
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "synthesizer"


class SynthesizerActivity(FanoutBase):
    """Orchestrates verdict synthesis from upstream agent observations."""

    AGENT_NAME = AGENT_NAME

    def __init__(self, redis_config: RedisConfig | None = None) -> None:
        super().__init__(redis_config)
        self._resolver = ObservationResolver()
        self._scorer = ConfidenceScorer()
        self._mapper = VerdictMapper()
        self._narrator = NarrativeGenerator()

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.SYNTHESIS_SIGNAL_COUNT

    def _primary_value_type(self) -> ValueType:
        return ValueType.NM

    def _timeout_value(self) -> str:
        return "0"

    async def _load_upstream_context(self, stream: ReasoningStream, run_id: str) -> ClaimContext:
        """Synthesizer reads all upstream streams directly in _execute; skip Phase 1 loading."""
        return ClaimContext()

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        # Step 1: Resolve observations
        await self._publish_progress(redis_client, run_id, "Resolving observations...")
        resolved = await self._resolver.resolve(run_id, stream)

        # Publish SYNTHESIS_SIGNAL_COUNT (seq 1)
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.SYNTHESIS_SIGNAL_COUNT,
            value=str(resolved.synthesis_signal_count),
            value_type=ValueType.NM,
            units="count",
            method="resolve_observations",
        )

        # Step 2: Compute confidence score
        await self._publish_progress(redis_client, run_id, "Computing confidence...")
        confidence_score = self._scorer.compute(resolved)

        # Publish CONFIDENCE_SCORE (seq 2) -- omitted if UNVERIFIABLE
        if confidence_score is not None:
            await self._publish_obs(
                stream,
                sk,
                run_id,
                code=ObservationCode.CONFIDENCE_SCORE,
                value=f"{confidence_score:.4f}",
                value_type=ValueType.NM,
                units="score",
                reference_range="0.0-1.0",
                method="compute_confidence",
            )

        # Step 3: Map verdict
        await self._publish_progress(redis_client, run_id, "Mapping verdict...")
        verdict_code, verdict_cwe, override_reason = self._mapper.map_verdict(
            confidence_score, resolved
        )

        # Publish VERDICT (seq 3)
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.VERDICT,
            value=verdict_cwe,
            value_type=ValueType.CWE,
            method="map_verdict",
        )

        # Step 4: Generate narrative
        await self._publish_progress(redis_client, run_id, "Generating narrative...")
        narrative = await self._narrator.generate(
            resolved=resolved,
            verdict=verdict_code,
            confidence_score=confidence_score,
            override_reason=override_reason,
            warnings=resolved.warnings,
            signal_count=resolved.synthesis_signal_count,
        )

        # Publish VERDICT_NARRATIVE (seq 4)
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.VERDICT_NARRATIVE,
            value=narrative,
            value_type=ValueType.TX,
            method="generate_narrative",
        )

        # Publish SYNTHESIS_OVERRIDE_REASON (seq 5)
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.SYNTHESIS_OVERRIDE_REASON,
            value=override_reason,
            value_type=ValueType.ST,
            method="map_verdict",
        )

        # Progress: verdict
        await self._publish_progress(
            redis_client,
            run_id,
            f"Verdict: {verdict_code}",
        )


# Agent registry integration
_HANDLER: SynthesizerActivity | None = None


def get_handler() -> SynthesizerActivity:
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = SynthesizerActivity()
    return _HANDLER
