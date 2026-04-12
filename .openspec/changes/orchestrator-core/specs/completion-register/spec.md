# Capability: completion-register

## Purpose

Track which agents have finished for a given run. Gate phase transitions in the Temporal workflow. Reconstruct completion state from Redis Streams after Temporal workflow replay without requiring any external persistent store beyond Redis Streams (NFR-007). The register operates within the workflow and is supplemented by a `rebuild_completion_register` Temporal activity for explicit recovery.

## Behaviour

### Data model

```python
# In-memory state (within the workflow or passed between activities)
_register: dict[str, str | None]
# _register[agent_name] = "F" | "X" | None
# None means the agent has been registered but has not yet emitted STOP
```

### Agent registration

When the workflow is about to dispatch an agent activity, it registers the agent in the completion register with status `None`. This establishes the set of expected agents so `is_phase_complete` knows what to wait for.

### Marking complete

When an agent activity returns, the workflow calls `mark_complete(agent, terminal_status)` where `terminal_status` is `"F"` (finished) or `"X"` (cancelled). This is the primary write path. Idempotent: calling `mark_complete` a second time with the same agent and status is a no-op.

### Phase completion check

`is_phase_complete(phase)` returns `True` when every agent registered for the given phase has a non-`None` terminal status. The register maps agent names to completion status; the phase definition (from the DAG) provides the list of agents expected in each phase.

### Restart recovery (Temporal replay)

On Temporal workflow replay, activity results are replayed from event history. The workflow rebuilds the register by re-executing the register updates from the replayed activity results. No explicit Redis scanning is needed for standard replay.

For explicit recovery (e.g., verifying consistency after a long outage), the `rebuild_completion_register` activity scans Redis Streams:

1. For each agent in every phase of the DAG: issue `XRANGE reasoning:{runId}:{agent} - +` via `ReasoningStream.read_range`.
2. Scan messages for a STOP message.
3. If found, include the agent with its terminal status in the result dict.

The workflow merges this result into the register. Agents that have already emitted STOP are not re-dispatched (their terminal status is present in the register).

Cost: one XRANGE per agent per recovery. At 11 agents and infrequent restarts, this is acceptable (NFR-007).

### Interface

```python
class CompletionRegister:
    def __init__(self) -> None: ...

    def register_agent(self, agent: str) -> None:
        """Mark agent as expected but not yet complete."""

    def mark_complete(self, agent: str, status: Literal["F", "X"]) -> None:
        """Record terminal status for agent. Idempotent."""

    def is_phase_complete(self, phase: Phase) -> bool:
        """Return True iff all agents in phase have terminal status."""

    def is_agent_complete(self, agent: str) -> bool:
        """Return True iff agent has terminal status."""

    def get_status(self, agent: str) -> str | None:
        """Return 'F', 'X', or None (not yet complete)."""

    def get_incomplete_agents(self, phase: Phase) -> list[str]:
        """Return agents in phase that have not yet completed."""

    def merge_from_rebuild(self, rebuild_result: dict[str, str | None]) -> None:
        """Merge results from rebuild_completion_register activity."""

    def reset(self) -> None:
        """Remove all completion state (called after run completes or is cancelled)."""


@activity.defn
async def rebuild_completion_register(
    run_id: str,
    agent_names: list[str],
) -> dict[str, str | None]:
    """Temporal activity: scan Redis Streams for STOP messages and return completion state."""
```

## Acceptance criteria

- `mark_complete` called twice with the same agent/status is a no-op (no duplicate registration).
- `is_phase_complete` returns `False` if any registered agent in the phase has status `None`.
- `is_phase_complete` returns `True` if all registered agents have status `"F"` or `"X"` (mix of F and X is valid).
- `rebuild_completion_register` activity correctly reconstructs completion state for a partially-complete run: agents that emitted STOP are returned with their status, agents that did not are returned as None.
- After merge from rebuild, `is_phase_complete` returns correct values consistent with the Redis Streams log.
- Temporal workflow replay correctly rebuilds the register from replayed activity results without re-scanning Redis.
- `reset` removes all in-memory state; subsequent `is_phase_complete` calls return False.
- `get_incomplete_agents` returns only agents with None status for the given phase.
