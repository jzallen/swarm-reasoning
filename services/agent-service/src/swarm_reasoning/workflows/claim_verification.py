"""ClaimVerificationWorkflow: three-phase DAG executor (ADR-0016).

Orchestrates 11 agents across three phases:
  Phase 1 (sequential): ingestion-agent, claim-detector, entity-extractor
  Phase 2a (parallel): claimreview-matcher, coverage-left, coverage-center,
                        coverage-right, domain-evidence
  Phase 2b (sequential): source-validator (needs Phase 2a URLs)
  Phase 3 (sequential): blindspot-detector, synthesizer

The workflow is deterministic — all I/O happens inside activities.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# Minimal timeout for cooperative cancellation checkpoints — just long enough
# to yield to the Temporal runtime so pending signals are delivered.
_CANCEL_CHECK_TIMEOUT = timedelta(milliseconds=1)

with workflow.unsafe.imports_passed_through():
    from swarm_reasoning.activities.run_agent import (
        AgentActivityInput,
        AgentActivityOutput,
        run_agent_activity,
    )
    from swarm_reasoning.activities.run_status import (
        RunStatusInput,
        RunStatusResult,
        cancel_run,
        fail_run,
        update_run_status,
    )
    from swarm_reasoning.completion.register import CompletionRegister
    from swarm_reasoning.workflows.dag import DAG, PhaseMode


@dataclass
class WorkflowInput:
    run_id: str
    claim_id: str
    session_id: str
    claim_text: str


@dataclass
class AgentResultSummary:
    agent_name: str
    terminal_status: str
    observation_count: int
    duration_ms: int


@dataclass
class WorkflowResult:
    run_id: str
    final_status: str  # "completed", "cancelled", "failed"
    verdict_id: str | None
    agent_results: list[AgentResultSummary]


# Default retry policy for agent activities
_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    non_retryable_error_types=[
        "InvalidClaimError",
        "InvalidRunTransition",
        "MissingApiKeyError",
        "StreamNotFoundError",
    ],
)


@dataclass(frozen=True)
class _PhaseTimeouts:
    """Per-phase timeout configuration for agent activities."""

    start_to_close: timedelta
    schedule_to_close: timedelta


# Per-phase timeouts (ADR-016 §4.5–4.7)
_PHASE_TIMEOUTS: dict[str, _PhaseTimeouts] = {
    "1": _PhaseTimeouts(
        start_to_close=timedelta(seconds=30),
        schedule_to_close=timedelta(seconds=60),
    ),
    "2a": _PhaseTimeouts(
        start_to_close=timedelta(seconds=45),
        schedule_to_close=timedelta(seconds=90),
    ),
    "2b": _PhaseTimeouts(
        start_to_close=timedelta(seconds=45),
        schedule_to_close=timedelta(seconds=90),
    ),
    "3": _PhaseTimeouts(
        start_to_close=timedelta(seconds=60),
        schedule_to_close=timedelta(seconds=120),
    ),
}

# Heartbeat timeout: 3x the 10s heartbeat interval per Temporal docs
_HEARTBEAT_TIMEOUT = timedelta(seconds=30)

# Agent-name → phase-id lookup (built from the static DAG)
_AGENT_PHASE: dict[str, str] = {
    agent: phase.id for phase in DAG for agent in phase.agents
}

# Status update activity has different timeouts (fast DB write)
_STATUS_TIMEOUT = timedelta(seconds=10)


@dataclass
class WorkflowStatus:
    run_id: str
    status: str  # "pending", "ingesting", "analyzing", "synthesizing", "completed", "cancelled", "failed"
    phase: str  # Current phase id: "1", "2a", "2b", "3", or "" if not started / terminal
    agents_complete: int
    agents_total: int


@workflow.defn
class ClaimVerificationWorkflow:
    """Orchestrates the three-phase agent pipeline as a Temporal workflow."""

    def __init__(self) -> None:
        self._register = CompletionRegister()
        self._agent_results: list[AgentResultSummary] = []
        self._status: str = "pending"
        self._phase: str = ""
        self._cancellation_requested: bool = False
        self._cancellation_reason: str = ""

    # --- Signals -------------------------------------------------------

    @workflow.signal
    async def request_cancellation(self, reason: str = "User requested cancellation") -> None:
        """External cancellation signal.  Sets a flag checked between phases."""
        workflow.logger.info("Cancellation signal received: %s", reason)
        self._cancellation_requested = True
        self._cancellation_reason = reason

    # --- Queries -------------------------------------------------------

    @workflow.query
    def status(self) -> WorkflowStatus:
        """Return the current workflow status and phase for external callers."""
        return WorkflowStatus(
            run_id="",  # Not stored; caller already knows the workflow id
            status=self._status,
            phase=self._phase,
            agents_complete=self._register.complete_count,
            agents_total=len(self._register.all_agents),
        )

    @workflow.query
    def current_phase(self) -> str:
        """Return the current phase id (e.g. '1', '2a', '2b', '3', or '')."""
        return self._phase

    # --- Main run ------------------------------------------------------

    @workflow.run
    async def run(self, input: WorkflowInput) -> WorkflowResult:
        # Register all agents
        for phase in DAG:
            self._register.register_agents(phase.agents)

        try:
            # Phase 1 — Sequential ingestion
            cancelled = await self._run_ingestion(input)
            if cancelled:
                return WorkflowResult(
                    run_id=input.run_id,
                    final_status="cancelled",
                    verdict_id=None,
                    agent_results=self._agent_results,
                )

            # Cooperative cancellation checkpoint before Phase 2
            if await self._check_cancellation(input.run_id):
                return WorkflowResult(
                    run_id=input.run_id,
                    final_status="cancelled",
                    verdict_id=None,
                    agent_results=self._agent_results,
                )

            # Phase 2a — Parallel fan-out + Phase 2b — Source validation
            await self._run_analysis(input)

            # Cooperative cancellation checkpoint before Phase 3
            if await self._check_cancellation(input.run_id):
                return WorkflowResult(
                    run_id=input.run_id,
                    final_status="cancelled",
                    verdict_id=None,
                    agent_results=self._agent_results,
                )

            # Phase 3 — Sequential synthesis
            await self._run_synthesis(input)

            # Transition: synthesizing -> completed
            await self._set_status(input.run_id, "completed")
            self._phase = ""

            return WorkflowResult(
                run_id=input.run_id,
                final_status="completed",
                verdict_id=None,  # Populated by synthesizer in later slices
                agent_results=self._agent_results,
            )

        except Exception as e:
            workflow.logger.error("Workflow failed for run %s: %s", input.run_id, e)
            await self._fail_run(input.run_id, str(e))
            self._status = "failed"
            self._phase = ""
            return WorkflowResult(
                run_id=input.run_id,
                final_status="failed",
                verdict_id=None,
                agent_results=self._agent_results,
            )

    # --- Phase methods -------------------------------------------------

    async def _run_ingestion(self, input: WorkflowInput) -> bool:
        """Phase 1: sequential ingestion. Returns True if the run was cancelled."""
        await self._set_status(input.run_id, "ingesting")
        self._phase = "1"

        for agent_name in DAG[0].agents:
            result = await self._dispatch_agent(agent_name, input)
            self._record_result(result)

            # Check-worthiness gate: if claim-detector returns X, cancel
            if agent_name == "claim-detector" and result.terminal_status == "X":
                await self._cancel_run(input.run_id, "Claim not check-worthy")
                self._status = "cancelled"
                self._phase = ""
                return True

        return False

    async def _run_analysis(self, input: WorkflowInput) -> None:
        """Phase 2a (parallel fan-out) + Phase 2b (sequential source validation)."""
        await self._set_status(input.run_id, "analyzing")

        # Phase 2a — Parallel fan-out (5 evidence-gathering agents)
        self._phase = "2a"
        phase_2a = DAG[1]
        assert phase_2a.mode == PhaseMode.PARALLEL
        fanout_results = await asyncio.gather(
            *[self._dispatch_agent(agent, input) for agent in phase_2a.agents],
            return_exceptions=True,
        )
        for agent_name, outcome in zip(phase_2a.agents, fanout_results):
            if isinstance(outcome, BaseException):
                workflow.logger.warning(
                    "Fan-out agent %s failed in run %s: %s",
                    agent_name,
                    input.run_id,
                    outcome,
                )
                self._register.mark_complete(agent_name, "X")
                self._agent_results.append(AgentResultSummary(
                    agent_name=agent_name,
                    terminal_status="X",
                    observation_count=0,
                    duration_ms=0,
                ))
            else:
                self._record_result(outcome)

        # Phase 2b — Source validation (sequential, after 2a)
        self._phase = "2b"
        for agent_name in DAG[2].agents:
            result = await self._dispatch_agent(agent_name, input)
            self._record_result(result)

    async def _run_synthesis(self, input: WorkflowInput) -> None:
        """Phase 3: sequential synthesis (blindspot-detector, synthesizer)."""
        await self._set_status(input.run_id, "synthesizing")
        self._phase = "3"

        for agent_name in DAG[3].agents:
            result = await self._dispatch_agent(agent_name, input)
            self._record_result(result)

    async def _dispatch_agent(
        self, agent_name: str, input: WorkflowInput
    ) -> AgentActivityOutput:
        """Dispatch a single agent as a Temporal activity.

        Selects start_to_close and schedule_to_close timeouts based on the
        agent's phase in the DAG.  heartbeat_timeout is fixed at 30 s (3×
        the 10 s heartbeat interval).
        """
        timeouts = _PHASE_TIMEOUTS[_AGENT_PHASE[agent_name]]
        agent_input = AgentActivityInput(
            agent_name=agent_name,
            run_id=input.run_id,
            claim_id=input.claim_id,
            session_id=input.session_id,
            claim_text=input.claim_text,
        )
        result = await workflow.execute_activity(
            run_agent_activity,
            agent_input,
            start_to_close_timeout=timeouts.start_to_close,
            heartbeat_timeout=_HEARTBEAT_TIMEOUT,
            schedule_to_close_timeout=timeouts.schedule_to_close,
            retry_policy=_RETRY_POLICY,
        )
        self._register.mark_complete(agent_name, result.terminal_status)
        return result

    def _record_result(self, result: AgentActivityOutput) -> None:
        """Record an agent result for the workflow output."""
        self._agent_results.append(AgentResultSummary(
            agent_name=result.agent_name,
            terminal_status=result.terminal_status,
            observation_count=result.observation_count,
            duration_ms=result.duration_ms,
        ))

    async def _check_cancellation(self, run_id: str) -> bool:
        """Cooperative cancellation checkpoint.

        Yields to the Temporal runtime via ``wait_condition`` so any pending
        cancellation signal is delivered before the flag is checked.  Returns
        True if cancellation was requested (and transitions the run to
        cancelled).
        """
        try:
            await workflow.wait_condition(
                lambda: self._cancellation_requested,
                timeout=_CANCEL_CHECK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            pass  # No signal within the window — continue normally

        if self._cancellation_requested:
            await self._cancel_run(run_id, self._cancellation_reason)
            self._status = "cancelled"
            self._phase = ""
            return True
        return False

    async def _set_status(self, run_id: str, new_status: str) -> None:
        """Update run status via activity and track locally for queries."""
        await workflow.execute_activity(
            update_run_status,
            RunStatusInput(run_id=run_id, new_status=new_status),
            start_to_close_timeout=_STATUS_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )
        self._status = new_status

    async def _cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel the run via activity."""
        await workflow.execute_activity(
            cancel_run,
            RunStatusInput(run_id=run_id, new_status="cancelled", reason=reason),
            start_to_close_timeout=_STATUS_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )

    async def _fail_run(self, run_id: str, reason: str) -> None:
        """Fail the run via activity."""
        await workflow.execute_activity(
            fail_run,
            RunStatusInput(run_id=run_id, new_status="failed", reason=reason),
            start_to_close_timeout=_STATUS_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )
