"""ClaimDetectorHandler — Temporal activity entry point for the claim-detector agent."""

from __future__ import annotations

import asyncio
import logging
import os
import time

import redis.asyncio as aioredis
from anthropic import AsyncAnthropic
from temporalio import activity

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
from swarm_reasoning.agents._utils import StreamNotFoundError, now_iso, register_handler
from swarm_reasoning.agents.claim_detector.normalizer import normalize_claim_text
from swarm_reasoning.agents.claim_detector.scorer import (
    CHECK_WORTHY_THRESHOLD,
    ScoreResult,
    score_claim_text,
)
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.status import EpistemicStatus
from swarm_reasoning.models.stream import ObsMessage, Phase, StartMessage, StopMessage
from swarm_reasoning.stream.base import ReasoningStream
from swarm_reasoning.stream.key import stream_key
from swarm_reasoning.stream.redis import RedisReasoningStream
from swarm_reasoning.temporal.errors import MissingApiKeyError

logger = logging.getLogger(__name__)

AGENT_NAME = "claim-detector"


async def _publish_progress(redis_client: aioredis.Redis, run_id: str, message: str) -> None:
    """Publish a progress event to progress:{runId} stream."""
    await redis_client.xadd(
        f"progress:{run_id}",
        {"agent": AGENT_NAME, "message": message, "timestamp": now_iso()},
    )


async def _read_claim_text(
    stream: ReasoningStream,
    run_id: str,
) -> str:
    """Read CLAIM_TEXT from the ingestion-agent stream.

    Returns:
        The final claim text string.

    Raises:
        StreamNotFoundError: If the ingestion stream has no CLAIM_TEXT observation.
    """
    ingestion_key = stream_key(run_id, "ingestion-agent")
    messages = await stream.read_range(ingestion_key)

    for msg in messages:
        if msg.type != "OBS":
            continue
        obs = msg.observation
        if obs.code == ObservationCode.CLAIM_TEXT and obs.status == "F":
            return obs.value

    raise StreamNotFoundError(f"No CLAIM_TEXT observation found in stream {ingestion_key}")


@register_handler("claim-detector")
class ClaimDetectorHandler:
    """Orchestrates claim normalization and check-worthiness scoring."""

    def __init__(
        self,
        redis_config: RedisConfig | None = None,
        anthropic_api_key: str | None = None,
    ) -> None:
        self._redis_config = redis_config or RedisConfig()
        api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError("ANTHROPIC_API_KEY is required for the claim-detector agent")
        self._api_key = api_key
        self._seq = 0

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput:
        """Execute the claim-detector: normalize claim, score check-worthiness, gate."""
        start = time.monotonic()
        run_id = input.run_id
        self._seq = 0

        stream = RedisReasoningStream(self._redis_config)
        redis_client = aioredis.Redis(
            host=self._redis_config.host,
            port=self._redis_config.port,
            db=self._redis_config.db,
        )
        anthropic_client = AsyncAnthropic(api_key=self._api_key)

        try:
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            sk = stream_key(run_id, AGENT_NAME)

            # Publish START
            await stream.publish(
                sk,
                StartMessage(
                    runId=run_id,
                    agent=AGENT_NAME,
                    phase=Phase.INGESTION,
                    timestamp=now_iso(),
                ),
            )

            # Read from ingestion stream
            claim_text = await _read_claim_text(stream, run_id)

            # Step 1: Normalize
            await _publish_progress(redis_client, run_id, "Normalizing claim text...")
            norm_result = normalize_claim_text(claim_text)

            note = None
            if norm_result.fallback_used:
                note = "normalization: fallback to raw text"

            # Publish CLAIM_NORMALIZED (seq=1, status=F)
            await self._publish_obs(
                stream,
                sk,
                run_id,
                code=ObservationCode.CLAIM_NORMALIZED,
                value=norm_result.normalized,
                value_type=ValueType.ST,
                status=EpistemicStatus.FINAL.value,
                method="normalize_claim",
                note=note,
            )

            # Step 2: Score check-worthiness and gate
            final_status, score_result = await self._score_and_gate(
                stream, sk, run_id, redis_client, anthropic_client, norm_result.normalized,
            )

            # Publish STOP
            await stream.publish(
                sk,
                StopMessage(
                    runId=run_id,
                    agent=AGENT_NAME,
                    finalStatus=final_status,
                    observationCount=self._seq,
                    timestamp=now_iso(),
                ),
            )

            heartbeat_task.cancel()
            duration_ms = int((time.monotonic() - start) * 1000)

            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status=final_status,
                observation_count=self._seq,
                duration_ms=duration_ms,
                check_worthiness_score=score_result.score,
            )
        finally:
            await stream.close()
            await redis_client.aclose()

    async def _score_and_gate(
        self,
        stream: ReasoningStream,
        sk: str,
        run_id: str,
        redis_client: aioredis.Redis,
        anthropic_client: AsyncAnthropic,
        normalized_text: str,
    ) -> tuple[str, ScoreResult]:
        """Score check-worthiness and apply the gate decision.

        Publishes CHECK_WORTHY_SCORE observations (preliminary + final) and
        progress events. Returns (final_status, score_result).
        """
        await _publish_progress(redis_client, run_id, "Scoring check-worthiness...")
        score_result = await score_claim_text(normalized_text, anthropic_client)

        score_note = (
            f"LLM rationale: {score_result.rationale[:480]}"
            if score_result.rationale
            else None
        )

        # Publish CHECK_WORTHY_SCORE with P status (preliminary pass-1 score)
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CHECK_WORTHY_SCORE,
            value=f"{score_result.passes[0]:.2f}",
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
            status=EpistemicStatus.PRELIMINARY.value,
            method="score_claim",
            note=score_note,
        )

        # Publish CHECK_WORTHY_SCORE with F status (final resolved score)
        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CHECK_WORTHY_SCORE,
            value=f"{score_result.score:.2f}",
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
            status=EpistemicStatus.FINAL.value,
            method="score_claim",
            note=score_note,
        )

        await _publish_progress(
            redis_client,
            run_id,
            f"Check-worthiness score: {score_result.score:.2f} "
            f"(threshold: {CHECK_WORTHY_THRESHOLD})",
        )

        # Gate decision
        if score_result.proceed:
            final_status = "F"
            await _publish_progress(
                redis_client, run_id, "Claim is check-worthy, proceeding to analysis"
            )
        else:
            final_status = "X"
            await _publish_progress(
                redis_client,
                run_id,
                f"Claim is not check-worthy "
                f"(score {score_result.score:.2f} < {CHECK_WORTHY_THRESHOLD}), "
                f"cancelling run",
            )

        return final_status, score_result

    async def _publish_obs(
        self,
        stream: ReasoningStream,
        sk: str,
        run_id: str,
        *,
        code: ObservationCode,
        value: str,
        value_type: ValueType,
        status: str = "F",
        method: str | None = None,
        note: str | None = None,
        units: str | None = None,
        reference_range: str | None = None,
    ) -> None:
        """Publish a single observation, auto-incrementing seq."""
        self._seq += 1
        await stream.publish(
            sk,
            ObsMessage(
                observation=Observation(
                    runId=run_id,
                    agent=AGENT_NAME,
                    seq=self._seq,
                    code=code,
                    value=value,
                    valueType=value_type,
                    status=status,
                    timestamp=now_iso(),
                    method=method,
                    note=note,
                    units=units,
                    referenceRange=reference_range,
                ),
            ),
        )

    @staticmethod
    async def _heartbeat_loop() -> None:
        """Send Temporal heartbeats every 10 seconds."""
        try:
            while True:
                await asyncio.sleep(10)
                activity.heartbeat()
        except asyncio.CancelledError:
            pass
