"""EntityExtractorHandler -- Temporal activity entry point for the entity-extractor agent."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis
from anthropic import AsyncAnthropic
from temporalio import activity

from swarm_reasoning.agents.entity_extractor.extractor import (
    LLMUnavailableError,
    extract_entities_llm,
)
from swarm_reasoning.agents.entity_extractor.publisher import (
    publish_entities,
    publish_error_stop,
)
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.models.stream import Phase, StartMessage
from swarm_reasoning.stream.base import ReasoningStream
from swarm_reasoning.stream.key import stream_key
from swarm_reasoning.stream.redis import RedisReasoningStream
from swarm_reasoning.temporal.activities import AgentActivityInput, AgentActivityOutput
from swarm_reasoning.temporal.errors import MissingApiKeyError

logger = logging.getLogger(__name__)

AGENT_NAME = "entity-extractor"


class StreamNotFoundError(Exception):
    """Raised when the claim-detector stream is not found (non-retryable)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _publish_progress(redis_client: aioredis.Redis, run_id: str, message: str) -> None:
    """Publish a progress event to progress:{runId} stream."""
    await redis_client.xadd(
        f"progress:{run_id}",
        {"agent": AGENT_NAME, "message": message, "timestamp": _now_iso()},
    )


async def _read_normalized_claim(
    stream: ReasoningStream,
    run_id: str,
) -> str:
    """Read CLAIM_NORMALIZED from the claim-detector stream.

    Returns the normalized claim text.

    Raises:
        StreamNotFoundError: If no CLAIM_NORMALIZED observation is found.
    """
    detector_key = stream_key(run_id, "claim-detector")
    messages = await stream.read_range(detector_key)

    for msg in messages:
        if msg.type != "OBS":
            continue
        obs = msg.observation
        if obs.code == ObservationCode.CLAIM_NORMALIZED and obs.status == "F":
            return obs.value

    raise StreamNotFoundError(
        f"No CLAIM_NORMALIZED observation found in stream {detector_key}"
    )


class EntityExtractorHandler:
    """Orchestrates entity extraction from normalized claim text."""

    def __init__(
        self,
        redis_config: RedisConfig | None = None,
        anthropic_api_key: str | None = None,
    ) -> None:
        self._redis_config = redis_config or RedisConfig()
        api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError("ANTHROPIC_API_KEY is required for the entity-extractor agent")
        self._api_key = api_key

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput:
        """Execute entity extraction: read normalized claim, extract entities, publish."""
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

            # Read normalized claim from claim-detector stream
            normalized_claim = await _read_normalized_claim(stream, run_id)

            # Progress: starting extraction
            await _publish_progress(redis_client, run_id, "Extracting named entities...")

            # Extract entities via LLM
            try:
                extraction_result = await extract_entities_llm(
                    normalized_claim, anthropic_client
                )
            except LLMUnavailableError:
                # Publish error STOP and re-raise for Temporal retry
                sk = stream_key(run_id, AGENT_NAME)
                await stream.publish(
                    sk,
                    StartMessage(
                        runId=run_id,
                        agent=AGENT_NAME,
                        phase=Phase.INGESTION,
                        timestamp=_now_iso(),
                    ),
                )
                await publish_error_stop(run_id, stream)
                raise

            # Publish START + entity observations + STOP
            observation_count = await publish_entities(run_id, extraction_result, stream)

            # Progress: summary
            total = (
                len(extraction_result.persons)
                + len(extraction_result.organizations)
                + len(extraction_result.dates)
                + len(extraction_result.locations)
                + len(extraction_result.statistics)
            )
            parts = []
            if extraction_result.persons:
                parts.append(f"{len(extraction_result.persons)} person(s)")
            if extraction_result.organizations:
                parts.append(f"{len(extraction_result.organizations)} org(s)")
            if extraction_result.dates:
                parts.append(f"{len(extraction_result.dates)} date(s)")
            if extraction_result.locations:
                parts.append(f"{len(extraction_result.locations)} location(s)")
            if extraction_result.statistics:
                parts.append(f"{len(extraction_result.statistics)} statistic(s)")

            summary = ", ".join(parts) if parts else "none"
            await _publish_progress(
                redis_client, run_id, f"Found {total} entities: {summary}"
            )
            await _publish_progress(redis_client, run_id, "Entity extraction complete")

            heartbeat_task.cancel()
            duration_ms = int((time.monotonic() - start) * 1000)

            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="F",
                observation_count=observation_count,
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


# ---------------------------------------------------------------------------
# Agent registry integration
# ---------------------------------------------------------------------------

_HANDLER: EntityExtractorHandler | None = None


def get_handler() -> EntityExtractorHandler:
    """Lazy-initialize and return the singleton handler."""
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = EntityExtractorHandler()
    return _HANDLER
