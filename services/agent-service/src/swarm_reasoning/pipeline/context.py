"""PipelineContext -- runtime dependency bag for LangGraph pipeline nodes (M0.2).

PipelineContext bundles the infrastructure handles (Redis client, stream
transport, heartbeat callback) that every pipeline node needs, without
coupling nodes to Temporal or Redis directly.  Nodes receive PipelineContext
via ``RunnableConfig["configurable"]["pipeline_context"]`` and use its
convenience methods to publish observations and progress events.

Scoped to the full pipeline run rather than a single agent.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import redis.asyncio as aioredis

from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage
from swarm_reasoning.stream.base import ReasoningStream
from swarm_reasoning.stream.key import stream_key

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PipelineContext:
    """Runtime context shared by all nodes in a single pipeline invocation.

    Attributes:
        stream: ReasoningStream transport for publishing observations.
        redis_client: Async Redis client for progress events.
        run_id: Current verification run identifier.
        session_id: Session that initiated the run.
        heartbeat_callback: Callable(node_name: str) forwarding heartbeats
            to Temporal's ``activity.heartbeat``.
    """

    stream: ReasoningStream
    redis_client: aioredis.Redis
    run_id: str
    session_id: str
    heartbeat_callback: Callable[[str], None]

    # Per-agent sequence counters (agents own independent sequences).
    _seq_counters: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------------
    # Sequence management
    # ------------------------------------------------------------------

    def next_seq(self, agent: str) -> int:
        """Atomically increment and return the next sequence number for *agent*."""
        with self._lock:
            self._seq_counters[agent] += 1
            return self._seq_counters[agent]

    # ------------------------------------------------------------------
    # Observation publishing
    # ------------------------------------------------------------------

    async def publish_observation(
        self,
        *,
        agent: str,
        code: ObservationCode,
        value: str,
        value_type: ValueType,
        status: str = "F",
        method: str | None = None,
        note: str | None = None,
        units: str | None = None,
        reference_range: str | None = None,
    ) -> int:
        """Publish a typed observation to ``reasoning:{run_id}:{agent}``.

        Returns the sequence number assigned to the observation.
        """
        seq = self.next_seq(agent)
        sk = stream_key(self.run_id, agent)
        await self.stream.publish(
            sk,
            ObsMessage(
                observation=Observation(
                    runId=self.run_id,
                    agent=agent,
                    seq=seq,
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
        return seq

    # ------------------------------------------------------------------
    # Progress publishing
    # ------------------------------------------------------------------

    async def publish_progress(self, agent: str, message: str) -> None:
        """Publish a human-readable progress event to ``progress:{run_id}``."""
        try:
            await self.redis_client.xadd(
                f"progress:{self.run_id}",
                {
                    "agent": agent,
                    "message": message,
                    "timestamp": _now_iso(),
                },
            )
        except Exception:
            logger.warning("Failed to publish progress for %s", agent)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def heartbeat(self, node_name: str) -> None:
        """Forward a heartbeat to Temporal with ``executing:{node_name}``."""
        self.heartbeat_callback(node_name)


# ------------------------------------------------------------------
# Helper: extract PipelineContext from LangGraph RunnableConfig
# ------------------------------------------------------------------


def get_pipeline_context(config: dict[str, Any]) -> PipelineContext:
    """Retrieve PipelineContext from a LangGraph RunnableConfig.

    Nodes call this at the top of their body::

        ctx = get_pipeline_context(config)
        await ctx.publish_observation(agent="intake", ...)

    Raises ``KeyError`` if the context was not injected.
    """
    return config["configurable"]["pipeline_context"]
