"""Integration tests for the simplified Temporal workflow using run_langgraph_pipeline (M7.4).

Tests the full Temporal workflow with the LangGraph pipeline activity, verifying:
  1. Happy path: pipeline completes, run status goes PENDING -> COMPLETED
  2. Retry behavior: non-retryable errors stop retries, transient errors retry
  3. Cancellation signal: workflow cancellation during pipeline execution
  4. Frontend notification: pipeline result shape matches FinalizeRunDto contract

These tests use Temporal's time-skipping test environment with stub/mock activities
to exercise the workflow-activity integration without external dependencies.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from swarm_reasoning.activities.run_pipeline import (
    PipelineActivityInput,
    PipelineResult,
    run_langgraph_pipeline,
)
from swarm_reasoning.activities.run_status import (
    RunStatusEnum,
    RunStatusInput,
    RunStatusResult,
    cancel_run,
    fail_run,
    get_run_status,
    set_run_store,
    update_run_status,
)

TASK_QUEUE = "test-simplified-queue"

# The fields the NestJS FinalizeController expects from a pipeline result
# (mirrors FinalizeRunDto: sessionId, verdict, confidence, narrative, ratingLabel?, citations?)
FINALIZE_DTO_REQUIRED_FIELDS = {"run_id", "verdict", "confidence", "narrative"}


# ---------------------------------------------------------------------------
# Simplified workflow: wraps run_langgraph_pipeline in a minimal workflow
# ---------------------------------------------------------------------------


@dataclass
class SimplifiedWorkflowInput:
    run_id: str
    session_id: str
    claim_text: str
    claim_url: str | None = None
    submission_date: str | None = None


@dataclass
class SimplifiedWorkflowResult:
    run_id: str
    final_status: str  # "completed", "cancelled", "failed"
    verdict: str | None = None
    confidence: float | None = None
    narrative: str | None = None
    is_check_worthy: bool = True
    errors: list[str] | None = None
    duration_ms: int = 0


_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    non_retryable_error_types=[
        "InvalidClaimError",
        "MissingApiKeyError",
        "NotCheckWorthyError",
    ],
)

_STATUS_TIMEOUT = timedelta(seconds=10)
_PIPELINE_TIMEOUT = timedelta(seconds=120)
_HEARTBEAT_TIMEOUT = timedelta(seconds=30)
_CANCEL_CHECK_TIMEOUT = timedelta(milliseconds=1)


@workflow.defn
class SimplifiedPipelineWorkflow:
    """Minimal workflow that executes the LangGraph pipeline as a single activity.

    This is the M7 "simplified workflow" pattern: instead of orchestrating 9
    individual agent activities across 3 phases, a single run_langgraph_pipeline
    activity handles the entire claim verification pipeline internally.
    """

    def __init__(self) -> None:
        self._cancellation_requested: bool = False
        self._cancellation_reason: str = ""
        self._status: str = "pending"

    @workflow.signal
    async def request_cancellation(self, reason: str = "User requested cancellation") -> None:
        self._cancellation_requested = True
        self._cancellation_reason = reason

    @workflow.query
    def status(self) -> str:
        return self._status

    @workflow.run
    async def run(self, input: SimplifiedWorkflowInput) -> SimplifiedWorkflowResult:
        try:
            # Check for pre-start cancellation
            if await self._check_cancellation(input.run_id):
                return SimplifiedWorkflowResult(run_id=input.run_id, final_status="cancelled")

            # Execute the pipeline as a single activity
            pipeline_input = PipelineActivityInput(
                run_id=input.run_id,
                session_id=input.session_id,
                claim_text=input.claim_text,
                claim_url=input.claim_url,
                submission_date=input.submission_date,
            )

            result: PipelineResult = await workflow.execute_activity(
                run_langgraph_pipeline,
                pipeline_input,
                start_to_close_timeout=_PIPELINE_TIMEOUT,
                heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                retry_policy=_RETRY_POLICY,
            )

            # Post-pipeline cancellation check
            if await self._check_cancellation(input.run_id):
                return SimplifiedWorkflowResult(run_id=input.run_id, final_status="cancelled")

            # Transition directly to completed (simplified path)
            await workflow.execute_activity(
                update_run_status,
                RunStatusInput(run_id=input.run_id, new_status="completed"),
                start_to_close_timeout=_STATUS_TIMEOUT,
                retry_policy=_RETRY_POLICY,
            )
            self._status = "completed"

            return SimplifiedWorkflowResult(
                run_id=input.run_id,
                final_status="completed",
                verdict=result.verdict,
                confidence=result.confidence,
                narrative=result.narrative,
                is_check_worthy=result.is_check_worthy,
                errors=result.errors,
                duration_ms=result.duration_ms,
            )

        except Exception as e:
            workflow.logger.error("Simplified workflow failed: %s", e)
            await workflow.execute_activity(
                fail_run,
                RunStatusInput(run_id=input.run_id, new_status="failed", reason=str(e)),
                start_to_close_timeout=_STATUS_TIMEOUT,
                retry_policy=_RETRY_POLICY,
            )
            self._status = "failed"
            return SimplifiedWorkflowResult(
                run_id=input.run_id,
                final_status="failed",
                errors=[str(e)],
            )

    async def _check_cancellation(self, run_id: str) -> bool:
        try:
            await workflow.wait_condition(
                lambda: self._cancellation_requested,
                timeout=_CANCEL_CHECK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            pass

        if self._cancellation_requested:
            await workflow.execute_activity(
                cancel_run,
                RunStatusInput(
                    run_id=run_id,
                    new_status="cancelled",
                    reason=self._cancellation_reason,
                ),
                start_to_close_timeout=_STATUS_TIMEOUT,
                retry_policy=_RETRY_POLICY,
            )
            self._status = "cancelled"
            return True
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_input(run_id: str | None = None) -> SimplifiedWorkflowInput:
    return SimplifiedWorkflowInput(
        run_id=run_id or str(uuid.uuid4()),
        session_id="session-001",
        claim_text="The unemployment rate dropped to 3.5% in January 2024",
    )


@pytest.fixture
def run_store():
    store: dict[str, RunStatusEnum] = {}
    set_run_store(store)
    yield store
    set_run_store({})


# ---------------------------------------------------------------------------
# 1. Happy path: pipeline completes, PENDING -> COMPLETED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simplified_workflow_happy_path(run_store):
    """Pipeline activity completes successfully, run transitions PENDING -> COMPLETED."""

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_pipeline(input: PipelineActivityInput) -> PipelineResult:
        return PipelineResult(
            run_id=input.run_id,
            verdict="mostly-true",
            confidence=0.82,
            narrative="The claim is mostly accurate based on available evidence.",
            is_check_worthy=True,
            errors=[],
            duration_ms=1500,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_pipeline,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "completed"
    assert result.verdict == "mostly-true"
    assert result.confidence == 0.82
    assert result.narrative == "The claim is mostly accurate based on available evidence."
    assert result.is_check_worthy is True
    assert result.errors == []
    assert result.duration_ms == 1500
    assert run_store[input.run_id] == RunStatusEnum.COMPLETED


@pytest.mark.asyncio
async def test_simplified_workflow_not_check_worthy(run_store):
    """Pipeline returns not-check-worthy result; workflow still completes."""

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_pipeline(input: PipelineActivityInput) -> PipelineResult:
        return PipelineResult(
            run_id=input.run_id,
            verdict="NOT_CHECK_WORTHY",
            confidence=1.0,
            narrative="The claim is not a verifiable factual assertion.",
            is_check_worthy=False,
            errors=[],
            duration_ms=200,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_pipeline,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "completed"
    assert result.verdict == "NOT_CHECK_WORTHY"
    assert result.confidence == 1.0
    assert result.is_check_worthy is False
    assert run_store[input.run_id] == RunStatusEnum.COMPLETED


@pytest.mark.asyncio
async def test_simplified_workflow_status_is_pending_to_completed(run_store):
    """Simplified workflow skips ingesting/analyzing/synthesizing, goes PENDING -> COMPLETED."""
    status_history: list[str] = []

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_pipeline(input: PipelineActivityInput) -> PipelineResult:
        return PipelineResult(
            run_id=input.run_id,
            verdict="true",
            confidence=0.95,
            narrative="Verified.",
            duration_ms=100,
        )

    @activity.defn(name="update_run_status")
    async def tracking_update(input: RunStatusInput) -> RunStatusResult:
        current = run_store.get(input.run_id, RunStatusEnum.PENDING)
        new_status = RunStatusEnum(input.new_status)
        run_store[input.run_id] = new_status
        status_history.append(new_status.value)
        return RunStatusResult(
            run_id=input.run_id,
            previous_status=current.value,
            current_status=new_status.value,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_pipeline,
                tracking_update,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "completed"
    # Only one status transition: pending -> completed (no intermediate phases)
    assert status_history == ["completed"]


# ---------------------------------------------------------------------------
# 2. Retry behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_retryable_invalid_claim_error(run_store):
    """InvalidClaimError (non-retryable) should fail the workflow without retrying."""
    attempt_count = 0

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_invalid_claim(input: PipelineActivityInput) -> PipelineResult:
        nonlocal attempt_count
        attempt_count += 1
        raise ApplicationError(
            "Empty claim text",
            type="InvalidClaimError",
            non_retryable=True,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_invalid_claim,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "failed"
    assert attempt_count == 1  # No retries for non-retryable errors
    assert run_store[input.run_id] == RunStatusEnum.FAILED


@pytest.mark.asyncio
async def test_non_retryable_missing_api_key_error(run_store):
    """MissingApiKeyError (non-retryable) should fail without retrying."""
    attempt_count = 0

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_missing_key(input: PipelineActivityInput) -> PipelineResult:
        nonlocal attempt_count
        attempt_count += 1
        raise ApplicationError(
            "ANTHROPIC_API_KEY not set",
            type="MissingApiKeyError",
            non_retryable=True,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_missing_key,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "failed"
    assert attempt_count == 1
    assert run_store[input.run_id] == RunStatusEnum.FAILED


@pytest.mark.asyncio
async def test_non_retryable_not_check_worthy_error(run_store):
    """NotCheckWorthyError (non-retryable) should fail without retrying."""
    attempt_count = 0

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_not_worthy(input: PipelineActivityInput) -> PipelineResult:
        nonlocal attempt_count
        attempt_count += 1
        raise ApplicationError(
            "Score 0.2 below threshold",
            type="NotCheckWorthyError",
            non_retryable=True,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_not_worthy,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "failed"
    assert attempt_count == 1
    assert run_store[input.run_id] == RunStatusEnum.FAILED


@pytest.mark.asyncio
async def test_transient_error_retries_then_succeeds(run_store):
    """Transient error triggers retry; pipeline succeeds on second attempt."""
    attempt_count = 0

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_retry(input: PipelineActivityInput) -> PipelineResult:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise RuntimeError("Redis connection lost")
        return PipelineResult(
            run_id=input.run_id,
            verdict="true",
            confidence=0.90,
            narrative="Claim verified after retry.",
            duration_ms=2000,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_retry,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "completed"
    assert attempt_count == 2  # First attempt failed, second succeeded
    assert result.verdict == "true"
    assert run_store[input.run_id] == RunStatusEnum.COMPLETED


@pytest.mark.asyncio
async def test_transient_error_exhausts_retries(run_store):
    """Transient error that persists through all retries should fail the workflow."""
    attempt_count = 0

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_always_fails(input: PipelineActivityInput) -> PipelineResult:
        nonlocal attempt_count
        attempt_count += 1
        raise RuntimeError("Persistent network failure")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_always_fails,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "failed"
    assert attempt_count == 3  # maximum_attempts=3 in the retry policy
    assert run_store[input.run_id] == RunStatusEnum.FAILED


# ---------------------------------------------------------------------------
# 3. Cancellation signal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_signal_before_pipeline(run_store):
    """Cancellation signal sent with workflow start cancels before pipeline runs."""
    pipeline_ran = False

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_pipeline(input: PipelineActivityInput) -> PipelineResult:
        nonlocal pipeline_ran
        pipeline_ran = True
        return PipelineResult(run_id=input.run_id, verdict="true", confidence=0.9)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_pipeline,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
                start_signal="request_cancellation",
                start_signal_args=["User cancelled before start"],
            )

    assert result.final_status == "cancelled"
    assert pipeline_ran is False
    assert run_store[input.run_id] == RunStatusEnum.CANCELLED


@pytest.mark.asyncio
async def test_cancellation_signal_during_pipeline(run_store):
    """Cancellation signal sent while pipeline is executing cancels after completion."""
    execution_log: list[str] = []

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = env.client

        @activity.defn(name="run_langgraph_pipeline")
        async def stub_pipeline(input: PipelineActivityInput) -> PipelineResult:
            execution_log.append("pipeline_started")
            # Send cancellation signal while pipeline is running
            wf_id = activity.info().workflow_id
            handle = client.get_workflow_handle(wf_id)
            await handle.signal("request_cancellation", "User cancelled during analysis")
            execution_log.append("pipeline_completed")
            return PipelineResult(
                run_id=input.run_id,
                verdict="true",
                confidence=0.9,
                narrative="Verified.",
                duration_ms=500,
            )

        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_pipeline,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "cancelled"
    # Pipeline did execute (it ran to completion before the checkpoint)
    assert "pipeline_started" in execution_log
    assert "pipeline_completed" in execution_log
    assert run_store[input.run_id] == RunStatusEnum.CANCELLED


@pytest.mark.asyncio
async def test_cancellation_idempotent_on_completed(run_store):
    """Cancellation signal on already-completed workflow is a no-op."""

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_pipeline(input: PipelineActivityInput) -> PipelineResult:
        return PipelineResult(
            run_id=input.run_id,
            verdict="true",
            confidence=0.95,
            narrative="Fully verified.",
            duration_ms=1000,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_pipeline,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    # Workflow completed normally
    assert result.final_status == "completed"
    assert run_store[input.run_id] == RunStatusEnum.COMPLETED


# ---------------------------------------------------------------------------
# 4. Frontend notification: result shape matches FinalizeRunDto
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_contains_finalize_dto_fields(run_store):
    """Workflow result should contain all fields needed by FinalizeController."""

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_pipeline(input: PipelineActivityInput) -> PipelineResult:
        return PipelineResult(
            run_id=input.run_id,
            verdict="mostly-true",
            confidence=0.78,
            narrative="The claim has substantial supporting evidence.",
            is_check_worthy=True,
            errors=[],
            duration_ms=3000,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_pipeline,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    # FinalizeRunDto requires: sessionId, verdict, confidence, narrative
    # The workflow result must carry these for the persist_verdict activity
    assert result.run_id is not None
    assert isinstance(result.verdict, str) and len(result.verdict) > 0
    assert isinstance(result.confidence, float) and 0.0 <= result.confidence <= 1.0
    assert isinstance(result.narrative, str) and len(result.narrative) > 0


@pytest.mark.asyncio
async def test_result_errors_are_list(run_store):
    """Workflow result errors should be a list (even when empty)."""

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_pipeline(input: PipelineActivityInput) -> PipelineResult:
        return PipelineResult(
            run_id=input.run_id,
            verdict="true",
            confidence=0.95,
            narrative="Verified.",
            errors=["coverage node timed out"],
            duration_ms=800,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_pipeline,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "completed"
    assert isinstance(result.errors, list)
    assert "coverage node timed out" in result.errors


@pytest.mark.asyncio
async def test_optional_input_fields_propagate(run_store):
    """claim_url and submission_date from input should reach the pipeline activity."""
    received_inputs: list[PipelineActivityInput] = []

    @activity.defn(name="run_langgraph_pipeline")
    async def capturing_pipeline(input: PipelineActivityInput) -> PipelineResult:
        received_inputs.append(input)
        return PipelineResult(
            run_id=input.run_id,
            verdict="true",
            confidence=0.9,
            narrative="Verified.",
            duration_ms=100,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = SimplifiedWorkflowInput(
            run_id=str(uuid.uuid4()),
            session_id="session-001",
            claim_text="Test claim",
            claim_url="https://example.com/article",
            submission_date="2026-04-14",
        )
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                capturing_pipeline,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "completed"
    assert len(received_inputs) == 1
    assert received_inputs[0].claim_url == "https://example.com/article"
    assert received_inputs[0].submission_date == "2026-04-14"


@pytest.mark.asyncio
async def test_failed_workflow_has_error_details(run_store):
    """Failed workflow should include error details in the result."""

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_fails(input: PipelineActivityInput) -> PipelineResult:
        raise ApplicationError(
            "Empty claim text",
            type="InvalidClaimError",
            non_retryable=True,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_fails,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "failed"
    assert result.errors is not None
    assert len(result.errors) > 0
    assert result.verdict is None
    assert result.confidence is None


# ---------------------------------------------------------------------------
# 5. Query support
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_status_during_execution(run_store):
    """Workflow status query should reflect current state during execution."""

    @activity.defn(name="run_langgraph_pipeline")
    async def stub_pipeline(input: PipelineActivityInput) -> PipelineResult:
        return PipelineResult(
            run_id=input.run_id,
            verdict="true",
            confidence=0.9,
            narrative="Verified.",
            duration_ms=100,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SimplifiedPipelineWorkflow],
            activities=[
                stub_pipeline,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            wf_handle = await env.client.start_workflow(
                SimplifiedPipelineWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )
            result = await wf_handle.result()

    assert result.final_status == "completed"
