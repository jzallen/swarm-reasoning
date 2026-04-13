"""SynthesizerHandler -- Temporal activity entry point for the synthesizer agent.

Final agent in the execution DAG: reads all 10 upstream agent streams,
resolves observations, computes confidence score, maps verdict,
generates narrative, and publishes 4-5 OBX observations + STOP.

Delegates all observation publishing to @tool definitions (ADR-004).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import redis.asyncio as aioredis
from temporalio import activity

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
from swarm_reasoning.agents._utils import now_iso, register_handler
from swarm_reasoning.agents.synthesizer.tools.map_verdict import map_verdict
from swarm_reasoning.agents.synthesizer.tools.narrate import generate_narrative
from swarm_reasoning.agents.synthesizer.tools.resolve import resolve_observations
from swarm_reasoning.agents.synthesizer.tools.score import compute_confidence
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.stream import Phase, StartMessage, StopMessage
from swarm_reasoning.stream.key import stream_key
from swarm_reasoning.stream.redis import RedisReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "synthesizer"


async def _publish_progress(redis_client: aioredis.Redis, run_id: str, message: str) -> None:
    """Publish a progress event to progress:{runId} stream."""
    try:
        await redis_client.xadd(
            f"progress:{run_id}",
            {"agent": AGENT_NAME, "message": message, "timestamp": now_iso()},
        )
    except Exception:
        logger.warning("Failed to publish progress for %s", AGENT_NAME)


@register_handler("synthesizer")
class SynthesizerHandler:
    """Orchestrates verdict synthesis from upstream agent observations.

    Delegates to four @tool definitions: resolve_observations,
    compute_confidence, map_verdict, generate_narrative. Each tool
    publishes its own observations via AgentContext.
    """

    def __init__(self, redis_config: RedisConfig | None = None) -> None:
        self._redis_config = redis_config or RedisConfig()

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput:
        """Execute the synthesizer: resolve, score, map, narrate."""
        start = time.monotonic()
        run_id = input.run_id

        stream = RedisReasoningStream(self._redis_config)
        redis_client = aioredis.Redis(
            host=self._redis_config.host,
            port=self._redis_config.port,
            db=self._redis_config.db,
        )

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
            )

            # Publish START
            await stream.publish(
                sk,
                StartMessage(
                    runId=run_id,
                    agent=AGENT_NAME,
                    phase=Phase.SYNTHESIS,
                    timestamp=now_iso(),
                ),
            )

            # Step 1: Resolve observations via @tool
            await _publish_progress(redis_client, run_id, "Resolving observations...")
            resolved_json = await resolve_observations.ainvoke(
                {"run_id": run_id, "context": agent_ctx}
            )
            resolved_data = json.loads(resolved_json)
            signal_count = resolved_data["synthesis_signal_count"]
            warnings = resolved_data["warnings"]

            # Step 2: Compute confidence score via @tool
            await _publish_progress(redis_client, run_id, "Computing confidence...")
            score_json = await compute_confidence.ainvoke(
                {"resolved_json": resolved_json, "context": agent_ctx}
            )
            confidence_score = json.loads(score_json)["score"]

            # Step 3: Map verdict via @tool
            await _publish_progress(redis_client, run_id, "Mapping verdict...")
            verdict_json = await map_verdict.ainvoke(
                {
                    "confidence_score": confidence_score,
                    "resolved_json": resolved_json,
                    "context": agent_ctx,
                }
            )
            verdict_data = json.loads(verdict_json)
            verdict_code = verdict_data["verdict_code"]
            override_reason = verdict_data["override_reason"]

            # Step 4: Generate narrative via @tool
            await _publish_progress(redis_client, run_id, "Generating narrative...")
            await generate_narrative.ainvoke(
                {
                    "resolved_json": resolved_json,
                    "verdict_code": verdict_code,
                    "confidence_score": confidence_score,
                    "override_reason": override_reason,
                    "signal_count": signal_count,
                    "warnings_json": json.dumps(warnings),
                    "context": agent_ctx,
                }
            )

            # Publish STOP
            await stream.publish(
                sk,
                StopMessage(
                    runId=run_id,
                    agent=AGENT_NAME,
                    finalStatus="F",
                    observationCount=agent_ctx.seq_counter,
                    timestamp=now_iso(),
                ),
            )

            # Progress: verdict
            await _publish_progress(redis_client, run_id, f"Verdict: {verdict_code}")

            heartbeat_task.cancel()
            duration_ms = int((time.monotonic() - start) * 1000)

            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="F",
                observation_count=agent_ctx.seq_counter,
                duration_ms=duration_ms,
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
