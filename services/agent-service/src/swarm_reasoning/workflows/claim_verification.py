"""ClaimVerificationWorkflow: single-activity pipeline executor (ADR-0023).

Orchestrates claim verification via a single LangGraph pipeline activity.
The pipeline graph (intake → evidence/coverage → validation → synthesizer)
runs entirely within one Temporal activity, replacing the old DAG-driven
multi-activity dispatch.

The workflow is deterministic — all I/O happens inside activities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from swarm_reasoning.activities.run_pipeline import (
        PipelineActivityInput,
        PipelineResult,
        run_langgraph_pipeline,
    )
    from swarm_reasoning.activities.run_status import (
        RunStatusInput,
        cancel_run,
        fail_run,
        update_run_status,
    )


@dataclass
class WorkflowInput:
    run_id: str
    claim_id: str
    session_id: str
    claim_text: str


@dataclass
class WorkflowResult:
    run_id: str
    final_status: str  # "completed", "cancelled", "failed"
    verdict: str | None
    confidence: float | None
    narrative: str | None


@dataclass
class WorkflowStatus:
    run_id: str
    status: str  # "pending", "ingesting", "completed", "cancelled", "failed"


# Retry policy for the pipeline activity (ADR-0023 §D7)
_PIPELINE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=2,
    non_retryable_error_types=[
        "InvalidClaimError",
        "MissingApiKeyError",
        "NotCheckWorthyError",
    ],
)

_STATUS_TIMEOUT = timedelta(seconds=10)
_STATUS_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_attempts=3,
    non_retryable_error_types=["InvalidRunTransition"],
)


@workflow.defn
class ClaimVerificationWorkflow:
    """Orchestrates claim verification via a single LangGraph pipeline activity (ADR-0023)."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._cancellation_requested: bool = False
        self._cancellation_reason: str = ""

    # --- Signals -------------------------------------------------------

    @workflow.signal
    async def request_cancellation(self, reason: str = "User requested cancellation") -> None:
        """External cancellation signal."""
        workflow.logger.info("Cancellation signal received: %s", reason)
        self._cancellation_requested = True
        self._cancellation_reason = reason

    # --- Queries -------------------------------------------------------

    @workflow.query
    def status(self) -> WorkflowStatus:
        """Return the current workflow status for external callers."""
        return WorkflowStatus(run_id="", status=self._status)

    # --- Main run ------------------------------------------------------

    @workflow.run
    async def run(self, input: WorkflowInput) -> WorkflowResult:
        try:
            # Check cancellation before starting
            if self._cancellation_requested:
                await self._cancel_run(input.run_id, self._cancellation_reason)
                return self._cancelled_result(input.run_id)

            # Transition: pending → ingesting
            await self._set_status(input.run_id, "ingesting")

            # Run the entire pipeline in ONE activity (ADR-0023)
            pipeline_input = PipelineActivityInput(
                run_id=input.run_id,
                session_id=input.session_id,
                claim_text=input.claim_text,
            )
            result = await workflow.execute_activity(
                run_langgraph_pipeline,
                pipeline_input,
                start_to_close_timeout=timedelta(seconds=180),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=_PIPELINE_RETRY,
            )

            # Transition: ingesting → completed
            await self._set_status(input.run_id, "completed")

            return WorkflowResult(
                run_id=input.run_id,
                final_status="completed",
                verdict=result.verdict,
                confidence=result.confidence,
                narrative=result.narrative,
            )

        except Exception as e:
            workflow.logger.error("Workflow failed for run %s: %s", input.run_id, e)
            await self._fail_run(input.run_id, str(e))
            return self._failed_result(input.run_id)

    # --- Helpers -------------------------------------------------------

    async def _set_status(self, run_id: str, new_status: str) -> None:
        await workflow.execute_activity(
            update_run_status,
            RunStatusInput(run_id=run_id, new_status=new_status),
            start_to_close_timeout=_STATUS_TIMEOUT,
            retry_policy=_STATUS_RETRY,
        )
        self._status = new_status

    async def _cancel_run(self, run_id: str, reason: str) -> None:
        await workflow.execute_activity(
            cancel_run,
            RunStatusInput(run_id=run_id, new_status="cancelled", reason=reason),
            start_to_close_timeout=_STATUS_TIMEOUT,
            retry_policy=_STATUS_RETRY,
        )
        self._status = "cancelled"

    async def _fail_run(self, run_id: str, reason: str) -> None:
        await workflow.execute_activity(
            fail_run,
            RunStatusInput(run_id=run_id, new_status="failed", reason=reason),
            start_to_close_timeout=_STATUS_TIMEOUT,
            retry_policy=_STATUS_RETRY,
        )
        self._status = "failed"

    def _cancelled_result(self, run_id: str) -> WorkflowResult:
        return WorkflowResult(
            run_id=run_id, final_status="cancelled",
            verdict=None, confidence=None, narrative=None,
        )

    def _failed_result(self, run_id: str) -> WorkflowResult:
        return WorkflowResult(
            run_id=run_id, final_status="failed",
            verdict=None, confidence=None, narrative=None,
        )
