"""ClaimVerificationWorkflow — three-phase DAG for agent orchestration (ADR-016).

Phase 1 (sequential ingestion):
    ingestion-agent → claim-detector → entity-extractor
    Check-worthiness gate: if claim-detector score < 0.4, cancel run.

Phase 2a (parallel fan-out):
    claimreview-matcher, coverage-left, coverage-center, coverage-right,
    domain-evidence — all dispatched concurrently.

Phase 2b (sequential):
    source-validator — needs cross-agent observation data from Phase 2a.

Phase 3 (sequential synthesis):
    blindspot-detector → synthesizer
"""

from __future__ import annotations

import asyncio
import dataclasses

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from swarm_reasoning.temporal.activities import (
        AgentActivityInput,
        AgentActivityOutput,
        run_agent_activity,
        task_queue_for_agent,
    )
    from swarm_reasoning.temporal.retry import (
        DEFAULT_RETRY_POLICY,
        PHASE_1_SCHEDULE_TO_CLOSE,
        PHASE_1_START_TO_CLOSE,
        PHASE_2_SCHEDULE_TO_CLOSE,
        PHASE_2_START_TO_CLOSE,
        PHASE_3_SCHEDULE_TO_CLOSE,
        PHASE_3_START_TO_CLOSE,
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECK_WORTHINESS_THRESHOLD = 0.4


class RunStatus:
    """Run lifecycle status values published at phase boundaries."""

    PENDING = "pending"
    INGESTING = "ingesting"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Workflow input/output contracts
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class WorkflowInput:
    """Input to ClaimVerificationWorkflow."""

    run_id: str
    session_id: str
    claim_text: str
    source_url: str | None = None
    source_date: str | None = None


@dataclasses.dataclass
class WorkflowResult:
    """Output from ClaimVerificationWorkflow."""

    run_id: str
    status: str
    phase_results: dict[str, str]  # agent_name -> terminal_status ("F" or "X")


# ---------------------------------------------------------------------------
# Workflow definition
# ---------------------------------------------------------------------------

# Phase agent assignments
_PHASE_1_AGENTS = ["ingestion-agent", "claim-detector", "entity-extractor"]
_PHASE_2A_AGENTS = [
    "claimreview-matcher",
    "coverage-left",
    "coverage-center",
    "coverage-right",
    "domain-evidence",
]
_PHASE_2B_AGENT = "source-validator"
_PHASE_3_AGENTS = ["blindspot-detector", "synthesizer"]


@workflow.defn
class ClaimVerificationWorkflow:
    """Temporal workflow orchestrating 11 agents across three phases."""

    def __init__(self) -> None:
        self._status = RunStatus.PENDING

    @workflow.signal
    async def workflow_completed(self) -> None:
        """Signal emitted when all phases finish or run is cancelled."""

    @workflow.signal
    async def workflow_failed(self) -> None:
        """Signal emitted on unrecoverable failure after retry exhaustion."""

    @workflow.query
    def status(self) -> str:
        """Query the current run status."""
        return self._status

    @workflow.run
    async def run(self, input: WorkflowInput) -> WorkflowResult:
        """Execute the three-phase claim verification DAG."""
        results: dict[str, str] = {}

        try:
            # ------ Phase 1: Sequential ingestion ------
            self._status = RunStatus.INGESTING

            for agent_name in _PHASE_1_AGENTS:
                output = await self._run_activity(
                    input=input,
                    agent_name=agent_name,
                    phase="ingestion",
                    start_to_close=PHASE_1_START_TO_CLOSE,
                    schedule_to_close=PHASE_1_SCHEDULE_TO_CLOSE,
                )
                results[agent_name] = output.terminal_status

                # Check-worthiness gate: cancel if score < threshold
                if agent_name == "claim-detector" and self._should_cancel(output):
                    self._status = RunStatus.CANCELLED
                    return WorkflowResult(
                        run_id=input.run_id,
                        status=RunStatus.CANCELLED,
                        phase_results=results,
                    )

            # ------ Phase 2a: Parallel fan-out ------
            self._status = RunStatus.ANALYZING

            phase_2a_tasks = [
                self._run_activity(
                    input=input,
                    agent_name=agent_name,
                    phase="fanout",
                    start_to_close=PHASE_2_START_TO_CLOSE,
                    schedule_to_close=PHASE_2_SCHEDULE_TO_CLOSE,
                )
                for agent_name in _PHASE_2A_AGENTS
            ]
            phase_2a_outputs: list[AgentActivityOutput] = list(
                await asyncio.gather(*phase_2a_tasks)
            )
            for output in phase_2a_outputs:
                results[output.agent_name] = output.terminal_status

            # ------ Phase 2b: Source validator (sequential, needs 2a data) ------
            output = await self._run_activity(
                input=input,
                agent_name=_PHASE_2B_AGENT,
                phase="fanout",
                start_to_close=PHASE_2_START_TO_CLOSE,
                schedule_to_close=PHASE_2_SCHEDULE_TO_CLOSE,
            )
            results[_PHASE_2B_AGENT] = output.terminal_status

            # ------ Phase 3: Sequential synthesis ------
            self._status = RunStatus.SYNTHESIZING

            for agent_name in _PHASE_3_AGENTS:
                output = await self._run_activity(
                    input=input,
                    agent_name=agent_name,
                    phase="synthesis",
                    start_to_close=PHASE_3_START_TO_CLOSE,
                    schedule_to_close=PHASE_3_SCHEDULE_TO_CLOSE,
                )
                results[agent_name] = output.terminal_status

            self._status = RunStatus.COMPLETED
            return WorkflowResult(
                run_id=input.run_id,
                status=RunStatus.COMPLETED,
                phase_results=results,
            )

        except Exception:
            self._status = RunStatus.FAILED
            return WorkflowResult(
                run_id=input.run_id,
                status=RunStatus.FAILED,
                phase_results=results,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _run_activity(
        self,
        input: WorkflowInput,
        agent_name: str,
        phase: str,
        start_to_close: object,
        schedule_to_close: object,
    ) -> AgentActivityOutput:
        """Dispatch a single agent activity with phase-appropriate timeouts."""
        return await workflow.execute_activity(
            run_agent_activity,
            AgentActivityInput(
                run_id=input.run_id,
                claim_text=input.claim_text,
                agent_name=agent_name,
                phase=phase,
                source_url=input.source_url,
                source_date=input.source_date,
            ),
            task_queue=task_queue_for_agent(agent_name),
            start_to_close_timeout=start_to_close,
            schedule_to_close_timeout=schedule_to_close,
            retry_policy=DEFAULT_RETRY_POLICY,
        )

    @staticmethod
    def _should_cancel(output: AgentActivityOutput) -> bool:
        """Return True if the check-worthiness gate should cancel the run."""
        return (
            output.check_worthiness_score is not None
            and output.check_worthiness_score < CHECK_WORTHINESS_THRESHOLD
        )
