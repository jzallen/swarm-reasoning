"""CompletionRegister: per-run bookkeeping for agent STOP signals (NFR-007).

Rebuilt from Redis Streams STOP messages on Temporal workflow replay.
"""

from __future__ import annotations


class CompletionRegister:
    """Tracks which agents have emitted STOP with terminal epistemic status (F or X).

    The register is an in-memory dict within the Temporal workflow, rebuilt on
    replay from activity results. For explicit recovery after a worker crash,
    use the rebuild_completion_register activity to scan Redis Streams.
    """

    def __init__(self) -> None:
        self._register: dict[str, str | None] = {}

    def register_agent(self, agent: str) -> None:
        """Register an agent as expected. Initial state is None (not yet complete)."""
        if agent not in self._register:
            self._register[agent] = None

    def register_agents(self, agents: list[str] | tuple[str, ...]) -> None:
        """Register multiple agents at once."""
        for agent in agents:
            self.register_agent(agent)

    def mark_complete(self, agent: str, terminal_status: str) -> None:
        """Mark an agent as complete with its terminal status (F or X). Idempotent."""
        if terminal_status not in ("F", "X"):
            raise ValueError(f"Terminal status must be 'F' or 'X', got: {terminal_status!r}")
        self._register[agent] = terminal_status

    def is_agent_complete(self, agent: str) -> bool:
        """Check if a specific agent has completed."""
        return self._register.get(agent) is not None

    def is_phase_complete(self, agents: list[str] | tuple[str, ...]) -> bool:
        """Check if all agents in a phase have completed."""
        return all(self._register.get(a) is not None for a in agents)

    def get_status(self, agent: str) -> str | None:
        """Get the terminal status for an agent, or None if not yet complete."""
        return self._register.get(agent)

    def get_incomplete_agents(self) -> list[str]:
        """Return agents that have not yet completed."""
        return [a for a, s in self._register.items() if s is None]

    def reset(self) -> None:
        """Clear all state."""
        self._register.clear()

    def merge_from_rebuild(self, rebuild_data: dict[str, str]) -> None:
        """Integrate results from rebuild_completion_register activity.

        Only marks agents as complete if they appear in the rebuild data
        with a valid terminal status.
        """
        for agent, status in rebuild_data.items():
            if status in ("F", "X"):
                self._register[agent] = status

    @property
    def all_agents(self) -> list[str]:
        """Return all registered agent names."""
        return list(self._register.keys())

    @property
    def complete_count(self) -> int:
        """Number of completed agents."""
        return sum(1 for s in self._register.values() if s is not None)
