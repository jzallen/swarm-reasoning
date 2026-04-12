"""Tests for ClaimVerificationWorkflow using Temporal's test environment."""

import uuid

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityResult
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
    """Full run with 11 stub agents should complete successfully."""

    @activity.defn(name="run_agent_activity")
    async def stub_agent(input: AgentActivityInput) -> AgentActivityResult:
        return AgentActivityResult(
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
        assert len(result.agent_results) == 11

        dispatched = {r.agent_name for r in result.agent_results}
        assert dispatched == set(ALL_AGENTS)
        assert run_store[input.run_id] == RunStatusEnum.COMPLETED


@pytest.mark.asyncio
async def test_workflow_check_worthiness_gate(run_store):
    """Claim-detector returning X should cancel the run early."""

    @activity.defn(name="run_agent_activity")
    async def stub_cancel(input: AgentActivityInput) -> AgentActivityResult:
        if input.agent_name == "claim-detector":
            return AgentActivityResult(
                agent_name=input.agent_name,
                terminal_status="X",
                observation_count=1,
                duration_ms=10,
            )
        return AgentActivityResult(
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
        assert "claimreview-matcher" not in dispatched
        assert "synthesizer" not in dispatched
        assert run_store[input.run_id] == RunStatusEnum.CANCELLED


@pytest.mark.asyncio
async def test_workflow_sequential_ordering(run_store):
    """Phase 1 agents must complete in order."""
    execution_order: list[str] = []

    @activity.defn(name="run_agent_activity")
    async def ordered_stub(input: AgentActivityInput) -> AgentActivityResult:
        execution_order.append(input.agent_name)
        return AgentActivityResult(
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

        # source-validator must come after the 5 fanout agents
        sv_idx = execution_order.index("source-validator")
        for fanout_agent in ["claimreview-matcher", "coverage-left", "coverage-center",
                             "coverage-right", "domain-evidence"]:
            assert execution_order.index(fanout_agent) < sv_idx

        # Phase 3 must come last
        bd_idx = execution_order.index("blindspot-detector")
        syn_idx = execution_order.index("synthesizer")
        assert bd_idx < syn_idx
        assert sv_idx < bd_idx


@pytest.mark.asyncio
async def test_workflow_status_transitions(run_store):
    """Verify run status transitions through all phases."""
    status_history: list[str] = []

    @activity.defn(name="run_agent_activity")
    async def stub_agent(input: AgentActivityInput) -> AgentActivityResult:
        return AgentActivityResult(
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
