"""IngestionAgentHandler — Temporal activity entry point for the ingestion agent."""

from __future__ import annotations

import asyncio
import os
import time

import redis.asyncio as aioredis
from anthropic import AsyncAnthropic
from temporalio import activity

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.ingestion_agent.tools.claim_intake import ingest_claim
from swarm_reasoning.agents.ingestion_agent.tools.domain_cls import (
    ClassificationServiceError,
    classify_domain,
)
from swarm_reasoning.agents.ingestion_agent.validation import ValidationError
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.stream.redis import RedisReasoningStream
from swarm_reasoning.temporal.errors import InvalidClaimError, MissingApiKeyError


@register_handler("ingestion-agent")
class IngestionAgentHandler:
    """Orchestrates the ingestion agent's two tools within a Temporal activity."""

    def __init__(
        self,
        redis_config: RedisConfig | None = None,
        anthropic_api_key: str | None = None,
    ) -> None:
        self._redis_config = redis_config or RedisConfig()
        api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError("ANTHROPIC_API_KEY is required for the ingestion agent")
        self._api_key = api_key

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput:
        """Execute the ingestion agent: validate claim, then classify domain."""
        start = time.monotonic()

        stream = RedisReasoningStream(self._redis_config)
        redis_client = aioredis.Redis(
            host=self._redis_config.host,
            port=self._redis_config.port,
            db=self._redis_config.db,
        )
        anthropic_client = AsyncAnthropic(api_key=self._api_key)

        try:
            # Heartbeat task for long-running LLM calls
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            try:
                ingestion_result = await ingest_claim(
                    run_id=input.run_id,
                    claim_text=input.claim_text,
                    source_url=input.source_url,
                    source_date=input.source_date,
                    stream=stream,
                    redis_client=redis_client,
                )
            except ValidationError as exc:
                raise InvalidClaimError(str(exc)) from exc

            if not ingestion_result.accepted:
                # Validation rejected the claim — stream is already closed with X
                heartbeat_task.cancel()
                duration_ms = int((time.monotonic() - start) * 1000)
                return AgentActivityOutput(
                    agent_name=input.agent_name,
                    terminal_status="X",
                    observation_count=1,
                    duration_ms=duration_ms,
                )

            # Classify domain
            try:
                cls_result = await classify_domain(
                    run_id=input.run_id,
                    claim_text=input.claim_text,
                    stream=stream,
                    anthropic_client=anthropic_client,
                    redis_client=redis_client,
                )
            except ClassificationServiceError:
                # Retryable — let Temporal retry the activity
                raise

            heartbeat_task.cancel()
            duration_ms = int((time.monotonic() - start) * 1000)

            # Total obs: 3 from ingest + 2 from classify (P+F) or 1 (fallback)
            total_obs = 3 + (2 if cls_result.confidence == "HIGH" else 1)

            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="F",
                observation_count=total_obs,
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
