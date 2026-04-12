"""FanoutBase -- shared base class for Phase 2a parallel fanout agents (ADR-0016).

Provides upstream context loading, observation publishing, progress events,
START/STOP lifecycle, and timeout enforcement. Subclasses override _execute().
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import redis.asyncio as aioredis
from temporalio import activity

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.status import EpistemicStatus
from swarm_reasoning.models.stream import ObsMessage, Phase, StartMessage, StopMessage
from swarm_reasoning.stream.base import ReasoningStream
from swarm_reasoning.stream.key import stream_key
from swarm_reasoning.stream.redis import RedisReasoningStream

logger = logging.getLogger(__name__)

# Internal timeout for agent execution (Temporal activity timeout is 45s)
INTERNAL_TIMEOUT_S = 30


@dataclass
class ClaimContext:
    """Upstream context loaded from Phase 1 agent streams."""

    normalized_claim: str = ""
    domain: str = "OTHER"
    persons: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    statistics: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StreamNotFoundError(Exception):
    """Raised when required upstream observations are not found."""


class FanoutBase(abc.ABC):
    """Abstract base for Phase 2a fanout agents.

    Subclasses must set AGENT_NAME and implement _execute().
    """

    AGENT_NAME: str = ""

    def __init__(self, redis_config: RedisConfig | None = None) -> None:
        self._redis_config = redis_config or RedisConfig()
        self._seq = 0

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput:
        """Execute the fanout agent: load context, run logic, publish results."""

        start = time.monotonic()
        run_id = input.run_id
        self._seq = 0

        stream = RedisReasoningStream(self._redis_config)
        redis_client = aioredis.Redis(
            host=self._redis_config.host,
            port=self._redis_config.port,
            db=self._redis_config.db,
        )

        try:
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            sk = stream_key(run_id, self.AGENT_NAME)

            # Publish START
            await stream.publish(
                sk,
                StartMessage(
                    runId=run_id,
                    agent=self.AGENT_NAME,
                    phase=Phase.FANOUT,
                    timestamp=_now_iso(),
                ),
            )

            # Load upstream context from Phase 1
            context = await self._load_upstream_context(stream, run_id)

            # Progress: starting
            await self._publish_progress(
                redis_client, run_id, f"Agent {self.AGENT_NAME} starting..."
            )

            # Execute with timeout
            final_status = "F"
            try:
                await asyncio.wait_for(
                    self._execute(stream, redis_client, run_id, sk, context),
                    timeout=INTERNAL_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.warning("Agent %s timed out after %ds", self.AGENT_NAME, INTERNAL_TIMEOUT_S)
                final_status = "X"
                await self._publish_obs(
                    stream,
                    sk,
                    run_id,
                    code=self._primary_code(),
                    value=self._timeout_value(),
                    value_type=self._primary_value_type(),
                    status=EpistemicStatus.CANCELLED.value,
                    note=f"Timeout after {INTERNAL_TIMEOUT_S}s",
                )
            except Exception:
                logger.exception("Agent %s failed", self.AGENT_NAME)
                final_status = "X"

            # Publish STOP
            await stream.publish(
                sk,
                StopMessage(
                    runId=run_id,
                    agent=self.AGENT_NAME,
                    finalStatus=final_status,
                    observationCount=self._seq,
                    timestamp=_now_iso(),
                ),
            )

            # Progress: done
            await self._publish_progress(
                redis_client,
                run_id,
                f"Agent {self.AGENT_NAME} completed ({self._seq} observations)",
            )

            heartbeat_task.cancel()
            duration_ms = int((time.monotonic() - start) * 1000)

            return AgentActivityOutput(
                agent_name=self.AGENT_NAME,
                terminal_status=final_status,
                observation_count=self._seq,
                duration_ms=duration_ms,
            )
        finally:
            await stream.close()
            await redis_client.aclose()

    @abc.abstractmethod
    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        """Subclass implementation: publish observations to stream."""

    def _primary_code(self) -> ObservationCode:
        """Return the primary observation code for timeout/error fallback."""
        raise NotImplementedError

    def _primary_value_type(self) -> ValueType:
        """Return the value type for the primary code."""
        return ValueType.CWE

    def _timeout_value(self) -> str:
        """Return a fallback value for timeout scenarios."""
        return "ABSENT^Timeout^FCK"

    async def _load_upstream_context(self, stream: ReasoningStream, run_id: str) -> ClaimContext:
        """Read claim context from Phase 1 agent streams."""
        ctx = ClaimContext()

        # Read from claim-detector: CLAIM_NORMALIZED
        detector_key = stream_key(run_id, "claim-detector")
        detector_msgs = await stream.read_range(detector_key)
        for msg in detector_msgs:
            if msg.type != "OBS":
                continue
            obs = msg.observation
            if obs.code == ObservationCode.CLAIM_NORMALIZED and obs.status == "F":
                ctx.normalized_claim = obs.value

        if not ctx.normalized_claim:
            raise StreamNotFoundError(f"No CLAIM_NORMALIZED in stream {detector_key}")

        # Read from ingestion-agent: CLAIM_DOMAIN
        ingestion_key = stream_key(run_id, "ingestion-agent")
        ingestion_msgs = await stream.read_range(ingestion_key)
        for msg in ingestion_msgs:
            if msg.type != "OBS":
                continue
            obs = msg.observation
            if obs.code == ObservationCode.CLAIM_DOMAIN and obs.status == "F":
                ctx.domain = obs.value

        # Read from entity-extractor: ENTITY_*
        extractor_key = stream_key(run_id, "entity-extractor")
        extractor_msgs = await stream.read_range(extractor_key)
        for msg in extractor_msgs:
            if msg.type != "OBS":
                continue
            obs = msg.observation
            if obs.status != "F":
                continue
            if obs.code == ObservationCode.ENTITY_PERSON:
                ctx.persons.append(obs.value)
            elif obs.code == ObservationCode.ENTITY_ORG:
                ctx.organizations.append(obs.value)
            elif obs.code == ObservationCode.ENTITY_DATE:
                ctx.dates.append(obs.value)
            elif obs.code == ObservationCode.ENTITY_LOCATION:
                ctx.locations.append(obs.value)
            elif obs.code == ObservationCode.ENTITY_STATISTIC:
                ctx.statistics.append(obs.value)

        return ctx

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
                    agent=self.AGENT_NAME,
                    seq=self._seq,
                    code=code,
                    value=value,
                    valueType=value_type,
                    status=status,
                    timestamp=_now_iso(),
                    method=method,
                    note=note,
                    units=units,
                    referenceRange=reference_range,
                ),
            ),
        )

    async def _publish_progress(
        self, redis_client: aioredis.Redis, run_id: str, message: str
    ) -> None:
        """Publish a progress event to progress:{runId}."""
        try:
            await redis_client.xadd(
                f"progress:{run_id}",
                {"agent": self.AGENT_NAME, "message": message, "timestamp": _now_iso()},
            )
        except Exception:
            logger.warning("Failed to publish progress for %s", self.AGENT_NAME)

    @staticmethod
    async def _heartbeat_loop() -> None:
        """Send Temporal heartbeats every 10 seconds."""
        try:
            while True:
                await asyncio.sleep(10)
                activity.heartbeat()
        except asyncio.CancelledError:
            pass
