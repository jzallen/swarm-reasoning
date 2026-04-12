"""Agent dispatch activity: invokes agent logic and manages stream lifecycle.

Each run_agent_activity call:
1. Publishes START to reasoning:{runId}:{agent}
2. Invokes the agent handler (stub for now — real agents in later slices)
3. Publishes STOP to reasoning:{runId}:{agent}
4. Heartbeats periodically to Temporal with stream-activity health check
5. Publishes progress events to progress:{runId}
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from temporalio import activity

from swarm_reasoning.models.stream import Phase as StreamPhase
from swarm_reasoning.stream.key import stream_key

# Heartbeat interval and warning threshold
HEARTBEAT_INTERVAL_S = 10
HEARTBEAT_WARNING_THRESHOLD_S = 30


@dataclass
class AgentActivityInput:
    """Standardized input for all agent activities.

    Used by both the workflow dispatcher and individual agent handlers.
    """

    agent_name: str
    run_id: str
    claim_text: str
    claim_id: str | None = None
    session_id: str | None = None
    phase: str | None = None  # "ingestion" | "fanout" | "synthesis"
    source_url: str | None = None
    source_date: str | None = None
    cross_agent_data: dict[str, Any] | None = None


@dataclass
class AgentActivityOutput:
    """Standardized output from all agent activities.

    Used by both the workflow (phase completion, gate decisions) and
    individual agent handlers.
    """

    agent_name: str
    terminal_status: str  # "F" (final) or "X" (cancelled)
    observation_count: int
    duration_ms: int
    check_worthiness_score: float | None = None


class AgentHandler(Protocol):
    """Protocol for agent handler implementations."""

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput: ...


# Registry of agent handlers. Populated at worker startup.
_agent_handlers: dict[str, AgentHandler] = {}


def register_agent_handler(agent_name: str, handler: AgentHandler) -> None:
    """Register an agent handler for dispatch."""
    _agent_handlers[agent_name] = handler


def get_agent_handler(agent_name: str) -> AgentHandler | None:
    """Look up a registered agent handler."""
    return _agent_handlers.get(agent_name)


# Redis stream interface for the activity. Injected at worker startup.
_stream_client: Any = None


def set_stream_client(client: Any) -> None:
    """Inject the ReasoningStream client for stream operations."""
    global _stream_client
    _stream_client = client


class MissingApiKeyError(Exception):
    """Non-retryable: required API key is not configured."""


class StreamNotFoundError(Exception):
    """Non-retryable: expected Redis Stream does not exist."""


class InvalidClaimError(Exception):
    """Non-retryable: claim data is invalid or malformed."""


# Retryable error types (LLM rate limits, timeouts, transient network)
RETRYABLE_ERRORS = (TimeoutError, ConnectionError, OSError)

# Non-retryable error types
NON_RETRYABLE_ERRORS = (MissingApiKeyError, StreamNotFoundError, InvalidClaimError, ValueError)


@activity.defn
async def run_agent_activity(input: AgentActivityInput) -> AgentActivityOutput:
    """Dispatch an agent: publish START, run handler, publish STOP, heartbeat."""
    start_time = time.monotonic()
    agent = input.agent_name
    run_id = input.run_id
    sk = stream_key(run_id, agent)

    activity.logger.info("Agent %s starting for run %s", agent, run_id)

    # Publish START message to agent stream
    if _stream_client is not None:
        from swarm_reasoning.models.stream import StartMessage

        phase = _resolve_phase(agent)
        start_msg = StartMessage(
            runId=run_id,
            agent=agent,
            phase=phase,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await _stream_client.publish(sk, start_msg)

    # Publish progress event
    await _publish_progress(run_id, agent, "started", f"Agent {agent} started")

    # Look up and invoke the agent handler
    handler = get_agent_handler(agent)
    if handler is not None:
        # Run agent with periodic heartbeating
        result = await _run_with_heartbeat(handler, input, sk)
    else:
        # No handler registered (stub mode) — just complete immediately
        activity.logger.warning("No handler for agent %s, completing as stub", agent)
        result = AgentActivityOutput(
            agent_name=agent,
            terminal_status="F",
            observation_count=0,
            duration_ms=0,
        )

    # Publish STOP message to agent stream
    if _stream_client is not None:
        from swarm_reasoning.models.stream import StopMessage

        stop_msg = StopMessage(
            runId=run_id,
            agent=agent,
            finalStatus=result.terminal_status,
            observationCount=result.observation_count,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await _stream_client.publish(sk, stop_msg)

    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    result.duration_ms = elapsed_ms

    # Publish progress event
    await _publish_progress(
        run_id, agent, "completed",
        f"Agent {agent} completed with status {result.terminal_status}"
    )

    activity.logger.info(
        "Agent %s completed for run %s: status=%s obs=%d duration=%dms",
        agent, run_id, result.terminal_status, result.observation_count, elapsed_ms,
    )
    return result


async def _run_with_heartbeat(
    handler: AgentHandler, input: AgentActivityInput, sk: str
) -> AgentActivityOutput:
    """Run the agent handler with periodic Temporal heartbeating."""
    task = asyncio.create_task(handler.run(input))
    last_heartbeat = time.monotonic()

    while not task.done():
        await asyncio.sleep(1)
        now = time.monotonic()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            # Check stream for recent activity (NFR-025)
            stream_ts = None
            if _stream_client is not None:
                latest = await _stream_client.read_latest(sk)
                if latest is not None:
                    stream_ts = "active"
            activity.heartbeat(f"{input.agent_name}:{stream_ts or 'no-activity'}")
            last_heartbeat = now

    return task.result()


async def _publish_progress(
    run_id: str, agent: str, status: str, message: str
) -> None:
    """Publish a progress event to progress:{runId}."""
    if _stream_client is not None:
        progress_key = f"progress:{run_id}"
        data = {
            "agent": agent,
            "status": status,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # Use raw Redis XADD for progress stream (not observation format)
            await _stream_client._redis.xadd(
                progress_key,
                {k: str(v) for k, v in data.items()},
            )
        except Exception:
            # Progress events are best-effort; don't fail the activity
            activity.logger.warning("Failed to publish progress event for %s", agent)


def _resolve_phase(agent: str) -> StreamPhase:
    """Resolve the stream Phase enum for an agent."""
    from swarm_reasoning.workflows.dag import DAG

    for phase in DAG:
        if agent in phase.agents:
            if phase.name == "ingestion":
                return StreamPhase.INGESTION
            elif phase.name in ("fanout", "fanout-validation"):
                return StreamPhase.FANOUT
            elif phase.name == "synthesis":
                return StreamPhase.SYNTHESIS
    return StreamPhase.INGESTION  # fallback
