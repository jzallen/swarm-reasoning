"""Blindspot detector Temporal activity -- coverage asymmetry analysis.

Phase 3 agent: receives cross-agent coverage data as Temporal activity input,
computes BLINDSPOT_SCORE, BLINDSPOT_DIRECTION, and CROSS_SPECTRUM_CORROBORATION,
then publishes observations to the agent's Redis Stream.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityResult
from swarm_reasoning.agents.blindspot_detector.analysis import (
    compute_blindspot_direction,
    compute_blindspot_score,
    compute_corroboration,
)
from swarm_reasoning.agents.blindspot_detector.models import CoverageSnapshot
from swarm_reasoning.agents.fanout_base import ClaimContext, FanoutBase
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "blindspot-detector"


class BlindspotDetectorActivity(FanoutBase):
    """Orchestrates coverage asymmetry analysis across spectrum segments."""

    AGENT_NAME = AGENT_NAME

    def __init__(self, redis_config: RedisConfig | None = None) -> None:
        super().__init__(redis_config)
        self._cross_agent_data: dict = {}

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.BLINDSPOT_SCORE

    def _primary_value_type(self) -> ValueType:
        return ValueType.NM

    def _timeout_value(self) -> str:
        return "1.0"

    async def run(self, input: AgentActivityInput) -> AgentActivityResult:
        """Override to extract cross_agent_data before running base flow."""
        self._cross_agent_data = input.cross_agent_data or {}
        return await super().run(input)

    async def _load_upstream_context(self, stream: ReasoningStream, run_id: str) -> ClaimContext:
        """Blindspot-detector uses cross_agent_data; skip Phase 1 context loading."""
        return ClaimContext()

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        # Progress: starting
        await self._publish_progress(redis_client, run_id, "Analyzing coverage blindspots...")

        # Graceful degradation: empty coverage dict (all agents timed out)
        coverage_data = self._cross_agent_data.get("coverage", {})
        if not coverage_data:
            await self._publish_degraded(stream, redis_client, run_id, sk)
            return

        # Parse coverage data from activity input
        coverage = CoverageSnapshot.from_activity_input(self._cross_agent_data)

        # Compute analysis
        score = compute_blindspot_score(coverage)
        direction = compute_blindspot_direction(coverage)
        corroboration, corroboration_note = compute_corroboration(coverage)

        # Publish BLINDSPOT_SCORE (seq 1)
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.BLINDSPOT_SCORE,
            value=str(score),
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
        )

        # Progress: score computed
        direction_label = direction.split("^")[0]
        await self._publish_progress(
            redis_client,
            run_id,
            f"Blindspot score: {score:.2f}, direction: {direction_label}",
        )

        # Publish BLINDSPOT_DIRECTION (seq 2)
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.BLINDSPOT_DIRECTION,
            value=direction,
            value_type=ValueType.CWE,
        )

        # Publish CROSS_SPECTRUM_CORROBORATION (seq 3)
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CROSS_SPECTRUM_CORROBORATION,
            value=corroboration,
            value_type=ValueType.CWE,
            note=corroboration_note,
        )

        # Progress: corroboration computed
        corroboration_label = corroboration.split("^")[0]
        await self._publish_progress(
            redis_client,
            run_id,
            f"Cross-spectrum corroboration: {corroboration_label}",
        )

    async def _publish_degraded(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
    ) -> None:
        """Publish degraded observations when coverage data is empty."""
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.BLINDSPOT_SCORE,
            value="1.0",
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
        )
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.BLINDSPOT_DIRECTION,
            value="NONE^No Blindspot^FCK",
            value_type=ValueType.CWE,
        )
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CROSS_SPECTRUM_CORROBORATION,
            value="FALSE^Not Corroborated^FCK",
            value_type=ValueType.CWE,
        )
        await self._publish_progress(
            redis_client,
            run_id,
            "Blindspot score: 1.00, direction: NONE (no coverage data)",
        )
        await self._publish_progress(
            redis_client,
            run_id,
            "Cross-spectrum corroboration: FALSE",
        )


# Agent registry integration
_HANDLER: BlindspotDetectorActivity | None = None


def get_handler() -> BlindspotDetectorActivity:
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = BlindspotDetectorActivity()
    return _HANDLER
