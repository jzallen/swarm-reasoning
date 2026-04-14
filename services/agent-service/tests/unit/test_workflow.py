"""Tests for ClaimVerificationWorkflow using Temporal's test environment."""

import uuid

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
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
from swarm_reasoning.workflows.claim_verification import (
    ClaimVerificationWorkflow,
    WorkflowInput,
    WorkflowStatus,
)
from swarm_reasoning.workflows.dag import ALL_AGENTS

TASK_QUEUE = "test-queue"


def _make_input(run_id: str | None = None) -> WorkflowInput:
    return WorkflowInput(
        run_id=run_id or str(uuid.uuid4()),
        claim_id="claim-001",
        session_id="session-001",
        claim_text="The earth is flat",
    )


@pytest.fixture
def run_store():
    store: dict[str, RunStatusEnum] = {}
    set_run_store(store)
    yield store
    set_run_store({})


@pytest.mark.asyncio
async def test_workflow_completes_all_agents(run_store):
    """Full run with 9 stub agents should complete successfully."""

    @activity.defn(name="run_agent_activity")
    async def stub_agent(input: AgentActivityInput) -> AgentActivityOutput:
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=3,
            duration_ms=50,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_agent,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

        assert result.final_status == "completed"
        assert len(result.agent_results) == 9

        dispatched = {r.agent_name for r in result.agent_results}
        assert dispatched == set(ALL_AGENTS)
        assert run_store[input.run_id] == RunStatusEnum.COMPLETED


@pytest.mark.asyncio
async def test_workflow_check_worthiness_gate(run_store):
    """Claim-detector returning X should cancel the run early."""

    @activity.defn(name="run_agent_activity")
    async def stub_cancel(input: AgentActivityInput) -> AgentActivityOutput:
        if input.agent_name == "claim-detector":
            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="X",
                observation_count=1,
                duration_ms=10,
            )
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=3,
            duration_ms=50,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_cancel,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

        assert result.final_status == "cancelled"
        dispatched = [r.agent_name for r in result.agent_results]
        assert "ingestion-agent" in dispatched
        assert "claim-detector" in dispatched
        assert "evidence" not in dispatched
        assert "synthesizer" not in dispatched
        assert run_store[input.run_id] == RunStatusEnum.CANCELLED


@pytest.mark.asyncio
async def test_workflow_sequential_ordering(run_store):
    """Phase 1 agents must complete in order."""
    execution_order: list[str] = []

    @activity.defn(name="run_agent_activity")
    async def ordered_stub(input: AgentActivityInput) -> AgentActivityOutput:
        execution_order.append(input.agent_name)
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=1,
            duration_ms=10,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                ordered_stub,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

        assert result.final_status == "completed"

        # Phase 1 must be sequential
        phase1 = execution_order[:3]
        assert phase1 == ["ingestion-agent", "claim-detector", "entity-extractor"]

        # Phase 2 fanout agents must come before Phase 3
        val_idx = execution_order.index("validation")
        for fanout_agent in ["evidence", "coverage-left", "coverage-center",
                             "coverage-right"]:
            assert execution_order.index(fanout_agent) < val_idx

        # Phase 3 must come last, validation before synthesizer
        syn_idx = execution_order.index("synthesizer")
        assert val_idx < syn_idx


@pytest.mark.asyncio
async def test_workflow_status_transitions(run_store):
    """Verify run status transitions through all phases."""
    status_history: list[str] = []

    @activity.defn(name="run_agent_activity")
    async def stub_agent(input: AgentActivityInput) -> AgentActivityOutput:
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=1,
            duration_ms=10,
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
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_agent,
                tracking_update,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

        assert result.final_status == "completed"
        assert status_history == ["ingesting", "analyzing", "synthesizing", "completed"]


@pytest.mark.asyncio
async def test_workflow_query_status_after_completion(run_store):
    """Query the status of a completed workflow."""

    @activity.defn(name="run_agent_activity")
    async def stub_agent(input: AgentActivityInput) -> AgentActivityOutput:
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=1,
            duration_ms=10,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_agent,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            wf_handle = await env.client.start_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )
            result = await wf_handle.result()

        assert result.final_status == "completed"


@pytest.mark.asyncio
async def test_workflow_query_current_phase_after_completion(run_store):
    """Query the current_phase of a completed workflow — should be empty."""

    @activity.defn(name="run_agent_activity")
    async def stub_agent(input: AgentActivityInput) -> AgentActivityOutput:
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=1,
            duration_ms=10,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_agent,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            wf_handle = await env.client.start_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )
            await wf_handle.result()


@pytest.mark.asyncio
async def test_workflow_query_cancelled_status(run_store):
    """Cancelled workflow should report cancelled status via query."""

    @activity.defn(name="run_agent_activity")
    async def stub_cancel(input: AgentActivityInput) -> AgentActivityOutput:
        if input.agent_name == "claim-detector":
            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="X",
                observation_count=1,
                duration_ms=10,
            )
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=3,
            duration_ms=50,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_cancel,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

        assert result.final_status == "cancelled"


# ---------------------------------------------------------------------------
# Cancellation signal tests (hq-423.31)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_signal_before_analysis(run_store):
    """Cancellation signal sent at workflow start cancels before Phase 2.

    Uses ``start_signal`` to deliver the signal atomically with the
    workflow start, guaranteeing it is part of the first workflow task.
    The signal handler fires before any activities run.
    """

    @activity.defn(name="run_agent_activity")
    async def stub_agent(input: AgentActivityInput) -> AgentActivityOutput:
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=2,
            duration_ms=20,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_agent,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            # start_signal delivers the signal with the first workflow task
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
                start_signal="request_cancellation",
                start_signal_args=["User cancelled the run"],
            )

    assert result.final_status == "cancelled"
    assert run_store[input.run_id] == RunStatusEnum.CANCELLED


@pytest.mark.asyncio
async def test_cancellation_signal_during_analysis(run_store):
    """Cancellation signal sent from inside a Phase 2a activity cancels before Phase 3.

    The activity sends the cancellation signal via the Temporal client.
    The remaining Phase 2 agents may still complete (already dispatched),
    but Phase 3 is skipped by the cooperative checkpoint.
    """
    execution_order: list[str] = []

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = env.client

        @activity.defn(name="run_agent_activity")
        async def stub_with_signal(input: AgentActivityInput) -> AgentActivityOutput:
            execution_order.append(input.agent_name)
            if input.agent_name == "coverage-left":
                wf_id = activity.info().workflow_id
                handle = client.get_workflow_handle(wf_id)
                await handle.signal("request_cancellation", "Cancelling during analysis")
            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="F",
                observation_count=2,
                duration_ms=20,
            )

        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_with_signal,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "cancelled"
    # Synthesis agents should not have run
    assert "synthesizer" not in execution_order
    assert "validation" not in execution_order
    assert run_store[input.run_id] == RunStatusEnum.CANCELLED


@pytest.mark.asyncio
async def test_cancellation_signal_idempotent_on_completed(run_store):
    """Cancellation signal on already-completed workflow is a no-op."""

    @activity.defn(name="run_agent_activity")
    async def stub_agent(input: AgentActivityInput) -> AgentActivityOutput:
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=1,
            duration_ms=10,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_agent,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    # Workflow completed normally — signal after completion doesn't change result
    assert result.final_status == "completed"
    assert run_store[input.run_id] == RunStatusEnum.COMPLETED


# ---------------------------------------------------------------------------
# Fan-out partial-failure tolerance tests (hq-423.32)
# ---------------------------------------------------------------------------

FANOUT_AGENTS = {
    "evidence",
    "coverage-left",
    "coverage-center",
    "coverage-right",
}


@pytest.mark.asyncio
async def test_fanout_single_agent_failure(run_store):
    """One fan-out agent raising should not abort the workflow.

    The failed agent gets AgentResultSummary(terminal_status='X'),
    while the remaining agents record normally.
    """

    @activity.defn(name="run_agent_activity")
    async def stub_one_fails(input: AgentActivityInput) -> AgentActivityOutput:
        if input.agent_name == "coverage-left":
            raise RuntimeError("coverage-left exploded")
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=3,
            duration_ms=50,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_one_fails,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "completed"
    assert len(result.agent_results) == 9

    by_name = {r.agent_name: r for r in result.agent_results}
    assert by_name["coverage-left"].terminal_status == "X"
    assert by_name["coverage-left"].observation_count == 0

    for agent in FANOUT_AGENTS - {"coverage-left"}:
        assert by_name[agent].terminal_status == "F"


@pytest.mark.asyncio
async def test_fanout_all_agents_fail(run_store):
    """All fan-out agents failing should still let synthesis proceed."""

    @activity.defn(name="run_agent_activity")
    async def stub_all_fanout_fail(input: AgentActivityInput) -> AgentActivityOutput:
        if input.agent_name in FANOUT_AGENTS:
            raise RuntimeError(f"{input.agent_name} exploded")
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=2,
            duration_ms=30,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_all_fanout_fail,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "completed"

    by_name = {r.agent_name: r for r in result.agent_results}
    for agent in FANOUT_AGENTS:
        assert by_name[agent].terminal_status == "X"
        assert by_name[agent].observation_count == 0

    # Synthesis agents still ran
    assert by_name["synthesizer"].terminal_status == "F"
    assert by_name["validation"].terminal_status == "F"


@pytest.mark.asyncio
async def test_fanout_mixed_results(run_store):
    """Mix of successes (F) and failures (X) in fan-out.

    Two agents fail, three succeed — workflow completes with partial results.
    """

    failing = {"coverage-right", "evidence"}

    @activity.defn(name="run_agent_activity")
    async def stub_mixed(input: AgentActivityInput) -> AgentActivityOutput:
        if input.agent_name in failing:
            raise RuntimeError(f"{input.agent_name} exploded")
        return AgentActivityOutput(
            agent_name=input.agent_name,
            terminal_status="F",
            observation_count=4,
            duration_ms=40,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        input = _make_input()
        run_store[input.run_id] = RunStatusEnum.PENDING

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ClaimVerificationWorkflow],
            activities=[
                stub_mixed,
                update_run_status,
                cancel_run,
                fail_run,
                get_run_status,
            ],
        ):
            result = await env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                input,
                id=f"test-{input.run_id}",
                task_queue=TASK_QUEUE,
            )

    assert result.final_status == "completed"
    assert len(result.agent_results) == 9

    by_name = {r.agent_name: r for r in result.agent_results}

    # Failed agents
    for agent in failing:
        assert by_name[agent].terminal_status == "X"
        assert by_name[agent].observation_count == 0

    # Successful fan-out agents
    for agent in FANOUT_AGENTS - failing:
        assert by_name[agent].terminal_status == "F"
        assert by_name[agent].observation_count == 4
