"""Activity contracts and base activity function for agent execution.

Each agent runs as a Temporal activity. The standardized input/output
contracts keep the workflow logic generic across all 11 agents.
"""

from __future__ import annotations

import dataclasses
import time

from temporalio import activity

# ---------------------------------------------------------------------------
# Agent registry — all 11 agents and their task queue naming
# ---------------------------------------------------------------------------

AGENT_NAMES: list[str] = [
    "ingestion-agent",
    "claim-detector",
    "entity-extractor",
    "claimreview-matcher",
    "coverage-left",
    "coverage-center",
    "coverage-right",
    "domain-evidence",
    "source-validator",
    "blindspot-detector",
    "synthesizer",
]

WORKFLOW_TASK_QUEUE = "claim-verification"


def task_queue_for_agent(agent_name: str) -> str:
    """Return the Temporal task queue name for an agent type.

    Format: agent:{agent-name}
    """
    return f"agent:{agent_name}"


# ---------------------------------------------------------------------------
# Activity input/output contracts
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AgentActivityInput:
    """Standardized input for all agent activities.

    All 11 agent activities receive this same input type.
    """

    run_id: str
    claim_text: str
    agent_name: str
    phase: str  # "ingestion" | "fanout" | "synthesis"
    source_url: str | None = None
    source_date: str | None = None


@dataclasses.dataclass
class AgentActivityOutput:
    """Standardized output from all agent activities.

    The workflow uses this output to determine phase completion,
    detect cancellations, and evaluate the check-worthiness gate.
    """

    agent_name: str
    terminal_status: str  # "F" (final) or "X" (cancelled)
    observation_count: int
    duration_ms: int
    check_worthiness_score: float | None = None


# ---------------------------------------------------------------------------
# Base activity function
# ---------------------------------------------------------------------------


@activity.defn
async def run_agent_activity(input: AgentActivityInput) -> AgentActivityOutput:
    """Execute an agent's reasoning session as a Temporal activity.

    This base implementation wraps the agent session protocol
    (START -> OBS[1..N] -> STOP). Actual agent logic is provided by
    per-agent slices that register executor functions in the agent
    executor registry.

    The activity ensures the START/STOP boundary is maintained even
    on failure — a STOP message with terminalStatus="X" is published
    if the agent encounters an error.
    """
    start = time.monotonic()

    activity.logger.info(
        "Starting agent activity: %s (run=%s, phase=%s)",
        input.agent_name,
        input.run_id,
        input.phase,
    )

    # Actual agent logic will be injected by per-agent implementation slices.
    # This stub returns a successful completion for infrastructure testing.
    duration_ms = int((time.monotonic() - start) * 1000)

    activity.logger.info(
        "Agent activity completed: %s (run=%s, duration=%dms)",
        input.agent_name,
        input.run_id,
        duration_ms,
    )

    return AgentActivityOutput(
        agent_name=input.agent_name,
        terminal_status="F",
        observation_count=0,
        duration_ms=duration_ms,
    )
