"""Completion register rebuild activity: XRANGE scan for STOP messages (NFR-007).

On Temporal workflow replay, the completion register is reconstructed from
replayed activity results. For explicit recovery (after a worker crash), this
activity scans Redis Streams via XRANGE for each agent and returns the
completion state.
"""

from __future__ import annotations

from dataclasses import dataclass

from temporalio import activity

from swarm_reasoning.stream.key import stream_key

# Pipeline node names that publish observations to Redis Streams.
# Replaces the old DAG.ALL_AGENTS after M8.3 migration to monolithic pipeline.
PIPELINE_NODES: tuple[str, ...] = (
    "intake",
    "evidence",
    "coverage",
    "validation",
    "synthesizer",
)


@dataclass
class RebuildInput:
    run_id: str
    agents: list[str] | None = None  # None = all agents


@dataclass
class RebuildResult:
    """Maps agent name -> terminal status ('F' or 'X'), only for completed agents."""

    completed: dict[str, str]


# Redis stream client, injected at worker startup
_stream_client = None


def set_stream_client(client: object) -> None:
    """Inject the ReasoningStream client."""
    global _stream_client
    _stream_client = client


@activity.defn
async def rebuild_completion_register(input: RebuildInput) -> RebuildResult:
    """Scan Redis Streams for STOP messages and return completion state.

    Cost: one XRANGE per agent per recovery. At 11 agents and infrequent
    restarts, this is acceptable (NFR-007).
    """
    agents = input.agents or list(PIPELINE_NODES)
    completed: dict[str, str] = {}

    if _stream_client is None:
        activity.logger.warning("No stream client configured, returning empty rebuild")
        return RebuildResult(completed=completed)

    for agent in agents:
        sk = stream_key(input.run_id, agent)
        try:
            messages = await _stream_client.read_range(sk)
            for msg in messages:
                if msg.type == "STOP":
                    completed[agent] = msg.final_status
                    break  # Only need the first STOP
        except Exception:
            activity.logger.warning("Failed to read stream for agent %s", agent, exc_info=True)

    activity.logger.info(
        "Rebuild for run %s: %d/%d agents completed",
        input.run_id, len(completed), len(agents),
    )
    return RebuildResult(completed=completed)
