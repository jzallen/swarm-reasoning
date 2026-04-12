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

with workflow.unsafe.imports_passed_through():
    from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
    from swarm_reasoning.activities.run_status import RunStatusInput, RunStatusResult
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
        "MissingApiKeyError",
        "StreamNotFoundError",
    ],
)

# Activity timeouts
_START_TO_CLOSE = timedelta(seconds=120)
_HEARTBEAT_TIMEOUT = timedelta(seconds=60)
_SCHEDULE_TO_CLOSE = timedelta(seconds=300)

# Status update activity has different timeouts (fast DB write)
_STATUS_TIMEOUT = timedelta(seconds=10)


@workflow.defn
class ClaimVerificationWorkflow:
    """Orchestrates the three-phase agent pipeline as a Temporal workflow."""

    def __init__(self) -> None:
        self._register = CompletionRegister()
        self._agent_results: list[AgentResultSummary] = []

    @workflow.run
    async def run(self, input: WorkflowInput) -> WorkflowResult:
        # Register all agents
        for phase in DAG:
            self._register.register_agents(phase.agents)

        # Transition: pending -> ingesting
        await self._update_status(input.run_id, "ingesting")

        try:
            # Phase 1 — Sequential ingestion
            for agent_name in DAG[0].agents:
                result = await self._dispatch_agent(agent_name, input)
                self._record_result(result)

                # Check-worthiness gate: if claim-detector returns X, cancel
                if agent_name == "claim-detector" and result.terminal_status == "X":
                    await self._cancel_run(input.run_id, "Claim not check-worthy")
                    return WorkflowResult(
                        run_id=input.run_id,
                        final_status="cancelled",
                        verdict_id=None,
                        agent_results=self._agent_results,
                    )

            # Transition: ingesting -> analyzing
            await self._update_status(input.run_id, "analyzing")

            # Phase 2a — Parallel fan-out (5 evidence-gathering agents)
            phase_2a = DAG[1]
            assert phase_2a.mode == PhaseMode.PARALLEL
            fanout_results = await asyncio.gather(
                *[self._dispatch_agent(agent, input) for agent in phase_2a.agents]
            )
            for r in fanout_results:
                self._record_result(r)

            # Phase 2b — Source validation (sequential, after 2a)
            for agent_name in DAG[2].agents:
                result = await self._dispatch_agent(agent_name, input)
                self._record_result(result)

            # Transition: analyzing -> synthesizing
            await self._update_status(input.run_id, "synthesizing")

            # Phase 3 — Sequential synthesis
            for agent_name in DAG[3].agents:
                result = await self._dispatch_agent(agent_name, input)
                self._record_result(result)

            # Transition: synthesizing -> completed
            await self._update_status(input.run_id, "completed")

            return WorkflowResult(
                run_id=input.run_id,
                final_status="completed",
                verdict_id=None,  # Populated by synthesizer in later slices
                agent_results=self._agent_results,
            )

        except Exception as e:
            workflow.logger.error("Workflow failed for run %s: %s", input.run_id, e)
            await self._fail_run(input.run_id, str(e))
            return WorkflowResult(
                run_id=input.run_id,
                final_status="failed",
                verdict_id=None,
                agent_results=self._agent_results,
            )

    async def _dispatch_agent(
        self, agent_name: str, input: WorkflowInput
    ) -> AgentActivityOutput:
        """Dispatch a single agent as a Temporal activity."""
        agent_input = AgentActivityInput(
            agent_name=agent_name,
            run_id=input.run_id,
            claim_id=input.claim_id,
            session_id=input.session_id,
            claim_text=input.claim_text,
        )
        result = await workflow.execute_activity(
            "run_agent_activity",
            agent_input,
            result_type=AgentActivityOutput,
            start_to_close_timeout=_START_TO_CLOSE,
            heartbeat_timeout=_HEARTBEAT_TIMEOUT,
            schedule_to_close_timeout=_SCHEDULE_TO_CLOSE,
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

    async def _update_status(self, run_id: str, new_status: str) -> None:
        """Update run status via activity."""
        await workflow.execute_activity(
            "update_run_status",
            RunStatusInput(run_id=run_id, new_status=new_status),
            result_type=RunStatusResult,
            start_to_close_timeout=_STATUS_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )

    async def _cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel the run via activity."""
        await workflow.execute_activity(
            "cancel_run",
            RunStatusInput(run_id=run_id, new_status="cancelled", reason=reason),
            result_type=RunStatusResult,
            start_to_close_timeout=_STATUS_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )

    async def _fail_run(self, run_id: str, reason: str) -> None:
        """Fail the run via activity."""
        await workflow.execute_activity(
            "fail_run",
            RunStatusInput(run_id=run_id, new_status="failed", reason=reason),
            result_type=RunStatusResult,
            start_to_close_timeout=_STATUS_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )
