"""AgentContext and ToolRuntime adapter for LangChain @tool functions.

AgentContext carries the stream connection, Redis client, and agent identity
needed by shared observation tools. ToolRuntime wraps AgentContext so it can
be injected into @tool-decorated functions via InjectedToolArg.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

import redis.asyncio as aioredis

from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage
from swarm_reasoning.stream.base import ReasoningStream


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentContext:
    """Runtime context available to every agent tool invocation.

    Attributes:
        stream: The ReasoningStream transport for publishing observations.
        redis_client: Async Redis client for progress events.
        run_id: Current verification run identifier.
        sk: Pre-computed stream key (reasoning:{run_id}:{agent_name}).
        agent_name: The agent publishing observations.
        seq_counter: Thread-safe observation sequence counter.
    """

    stream: ReasoningStream
    redis_client: aioredis.Redis
    run_id: str
    sk: str
    agent_name: str
    seq_counter: int = field(default=0)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def next_seq(self) -> int:
        """Atomically increment and return the next sequence number."""
        with self._lock:
            self.seq_counter += 1
            return self.seq_counter

    async def publish_obs(
        self,
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
        seq = self.next_seq()
        await self.stream.publish(
            self.sk,
            ObsMessage(
                observation=Observation(
                    runId=self.run_id,
                    agent=self.agent_name,
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


class ToolRuntime:
    """Adapter that holds AgentContext for injection into LangChain tools.

    Usage::

        ctx = AgentContext(stream=..., redis_client=..., ...)
        runtime = ToolRuntime(ctx)
        # Pass runtime.context to tools via InjectedToolArg
    """

    def __init__(self, context: AgentContext) -> None:
        self._context = context

    @property
    def context(self) -> AgentContext:
        return self._context
