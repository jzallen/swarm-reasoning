"""ClaimDetectorHandler — Temporal activity entry point for the claim-detector agent."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis
from anthropic import AsyncAnthropic
from temporalio import activity

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
from swarm_reasoning.agents._utils import StreamNotFoundError, now_iso, register_handler
from swarm_reasoning.agents.claim_detector.tools.normalize import normalize_claim
from swarm_reasoning.agents.claim_detector.tools.score import score_check_worthiness
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.models.stream import Phase, StartMessage, StopMessage
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
    """Orchestrates claim normalization and check-worthiness scoring.

    Delegates to the normalize_claim and score_check_worthiness @tool
    definitions for observation publishing via AgentContext.
    """

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

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput:
        """Execute the claim-detector: normalize claim, score check-worthiness, gate."""
        start = time.monotonic()
        run_id = input.run_id

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

            # Create AgentContext for @tool observation publishing
            agent_ctx = AgentContext(
                stream=stream,
                redis_client=redis_client,
                run_id=run_id,
                sk=sk,
                agent_name=AGENT_NAME,
                anthropic_client=anthropic_client,
            )

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

            # Step 1: Normalize via @tool
            await _publish_progress(redis_client, run_id, "Normalizing claim text...")
            normalized = await normalize_claim.ainvoke(
                {"claim_text": claim_text, "context": agent_ctx}
            )

            # Step 2: Score check-worthiness via @tool
            await _publish_progress(redis_client, run_id, "Scoring check-worthiness...")
            score_json = await score_check_worthiness.ainvoke(
                {
                    "normalized_text": normalized,
                    "context": agent_ctx,
                    "anthropic_client": anthropic_client,
                }
            )
            score_data = json.loads(score_json)
            score_value = score_data["score"]
            threshold = score_data["threshold"]
            proceed = score_data["proceed"]

            await _publish_progress(
                redis_client,
                run_id,
                f"Check-worthiness score: {score_value:.2f} "
                f"(threshold: {threshold})",
            )

            # Gate decision
            if proceed:
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
                    f"(score {score_value:.2f} < {threshold}), "
                    f"cancelling run",
                )

            # Publish STOP
            await stream.publish(
                sk,
                StopMessage(
                    runId=run_id,
                    agent=AGENT_NAME,
                    finalStatus=final_status,
                    observationCount=agent_ctx.seq_counter,
                    timestamp=now_iso(),
                ),
            )

            heartbeat_task.cancel()
            duration_ms = int((time.monotonic() - start) * 1000)

            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status=final_status,
                observation_count=agent_ctx.seq_counter,
                duration_ms=duration_ms,
                check_worthiness_score=score_value,
            )
        finally:
            await stream.close()
            await redis_client.aclose()

    @staticmethod
    async def _heartbeat_loop() -> None:
        """Send Temporal heartbeats every 10 seconds."""
        try:
            while True:
                await asyncio.sleep(10)
                activity.heartbeat()
        except asyncio.CancelledError:
            pass
