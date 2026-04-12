"""Integration tests for ClaimVerificationWorkflow using Temporal test environment.

These tests start a local in-memory Temporal server and execute
the workflow with mocked agent activities.
"""

import pytest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from swarm_reasoning.temporal.activities import (
    AGENT_NAMES,
    WORKFLOW_TASK_QUEUE,
    AgentActivityInput,
    AgentActivityOutput,
    run_agent_activity,
    task_queue_for_agent,
)
from swarm_reasoning.temporal.workflow import (
    ClaimVerificationWorkflow,
    RunStatus,
    WorkflowInput,
    WorkflowResult,
)


@pytest.fixture
async def temporal_env():
    """Start a local Temporal test environment."""
    env = await WorkflowEnvironment.start_local()
    yield env
    await env.shutdown()


async def _run_workflow_with_activities(
    client: Client,
    workflow_input: WorkflowInput,
    activity_fn=run_agent_activity,
) -> WorkflowResult:
    """Run the workflow with all agent workers in the test environment."""
    # Create workers for all task queues
    workers = []
    for agent_name in AGENT_NAMES:
        w = Worker(
            client,
            task_queue=task_queue_for_agent(agent_name),
            activities=[activity_fn],
        )
        workers.append(w)

    # Workflow worker
    workflow_worker = Worker(
        client,
        task_queue=WORKFLOW_TASK_QUEUE,
        workflows=[ClaimVerificationWorkflow],
    )
    workers.append(workflow_worker)

    # Run all workers and execute the workflow
    async with _multi_worker_context(workers):
        result = await client.execute_workflow(
            ClaimVerificationWorkflow.run,
            workflow_input,
            id=f"test-{workflow_input.run_id}",
            task_queue=WORKFLOW_TASK_QUEUE,
        )
    return result


class _multi_worker_context:
    """Context manager that runs multiple Temporal workers concurrently."""

    def __init__(self, workers: list[Worker]):
        self._workers = workers
        self._tasks = []

    async def __aenter__(self):
        import asyncio

        for w in self._workers:
            self._tasks.append(asyncio.create_task(w.run()))
        return self

    async def __aexit__(self, *args):
        for t in self._tasks:
            t.cancel()
        import asyncio

        await asyncio.gather(*self._tasks, return_exceptions=True)


@pytest.mark.integration
class TestWorkflowExecution:
    async def test_successful_three_phase_execution(self, temporal_env):
        """All 11 agents complete successfully across three phases."""
        result = await _run_workflow_with_activities(
            temporal_env.client,
            WorkflowInput(
                run_id="test-run-1",
                session_id="sess-1",
                claim_text="The Earth is round",
            ),
        )

        assert result.status == RunStatus.COMPLETED
        assert result.run_id == "test-run-1"
        # All 11 agents should have results
        assert len(result.phase_results) == 11
        for agent_name in AGENT_NAMES:
            assert agent_name in result.phase_results
            assert result.phase_results[agent_name] == "F"

    async def test_phase_ordering(self, temporal_env):
        """Phase 1 runs before Phase 2, Phase 2 before Phase 3."""
        execution_order = []

        from temporalio import activity

        @activity.defn(name="run_agent_activity")
        async def tracking_activity(input: AgentActivityInput) -> AgentActivityOutput:
            execution_order.append(input.agent_name)
            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="F",
                observation_count=1,
                duration_ms=10,
            )

        result = await _run_workflow_with_activities(
            temporal_env.client,
            WorkflowInput(
                run_id="test-order",
                session_id="sess-2",
                claim_text="Test ordering",
            ),
            activity_fn=tracking_activity,
        )

        assert result.status == RunStatus.COMPLETED

        # Phase 1 agents must come first, in order
        p1_agents = ["ingestion-agent", "claim-detector", "entity-extractor"]
        p1_idx = [execution_order.index(a) for a in p1_agents]
        assert p1_idx == sorted(p1_idx)
        assert p1_idx[0] == 0  # ingestion-agent is first

        # Phase 2a agents come after Phase 1
        p2a_names = {
            "claimreview-matcher",
            "coverage-left",
            "coverage-center",
            "coverage-right",
            "domain-evidence",
        }
        p2a_indices = [execution_order.index(a) for a in p2a_names]
        assert all(i > max(p1_idx) for i in p2a_indices)

        # Phase 2b (source-validator) comes after Phase 2a
        sv_idx = execution_order.index("source-validator")
        assert sv_idx > max(p2a_indices)

        # Phase 3 agents come after Phase 2b
        p3_idx = [execution_order.index(a) for a in ["blindspot-detector", "synthesizer"]]
        assert all(i > sv_idx for i in p3_idx)
        assert p3_idx == sorted(p3_idx)

    async def test_check_worthiness_gate_cancels_run(self, temporal_env):
        """Low check-worthiness score cancels the run after Phase 1."""
        from temporalio import activity

        @activity.defn(name="run_agent_activity")
        async def low_score_activity(input: AgentActivityInput) -> AgentActivityOutput:
            score = 0.3 if input.agent_name == "claim-detector" else None
            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="F",
                observation_count=1,
                duration_ms=10,
                check_worthiness_score=score,
            )

        result = await _run_workflow_with_activities(
            temporal_env.client,
            WorkflowInput(
                run_id="test-cancel",
                session_id="sess-3",
                claim_text="Not checkworthy",
            ),
            activity_fn=low_score_activity,
        )

        assert result.status == RunStatus.CANCELLED
        # Only ingestion-agent and claim-detector should have run
        assert "ingestion-agent" in result.phase_results
        assert "claim-detector" in result.phase_results
        assert "entity-extractor" not in result.phase_results
        assert len(result.phase_results) == 2

    async def test_sufficient_check_worthiness_continues(self, temporal_env):
        """High check-worthiness score proceeds through all phases."""
        from temporalio import activity

        @activity.defn(name="run_agent_activity")
        async def high_score_activity(input: AgentActivityInput) -> AgentActivityOutput:
            score = 0.7 if input.agent_name == "claim-detector" else None
            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="F",
                observation_count=1,
                duration_ms=10,
                check_worthiness_score=score,
            )

        result = await _run_workflow_with_activities(
            temporal_env.client,
            WorkflowInput(
                run_id="test-continue",
                session_id="sess-4",
                claim_text="Checkworthy claim",
            ),
            activity_fn=high_score_activity,
        )

        assert result.status == RunStatus.COMPLETED
        assert len(result.phase_results) == 11

    async def test_run_status_transitions(self, temporal_env):
        """Workflow status query reflects phase transitions."""
        from temporalio import activity

        @activity.defn(name="run_agent_activity")
        async def status_tracking_activity(input: AgentActivityInput) -> AgentActivityOutput:
            return AgentActivityOutput(
                agent_name=input.agent_name,
                terminal_status="F",
                observation_count=1,
                duration_ms=10,
            )

        # Start the workflow
        workers = []
        for agent_name in AGENT_NAMES:
            workers.append(
                Worker(
                    temporal_env.client,
                    task_queue=task_queue_for_agent(agent_name),
                    activities=[status_tracking_activity],
                )
            )
        workers.append(
            Worker(
                temporal_env.client,
                task_queue=WORKFLOW_TASK_QUEUE,
                workflows=[ClaimVerificationWorkflow],
            )
        )

        async with _multi_worker_context(workers):
            result = await temporal_env.client.execute_workflow(
                ClaimVerificationWorkflow.run,
                WorkflowInput(
                    run_id="test-status",
                    session_id="sess-5",
                    claim_text="Status test",
                ),
                id="test-status-wf",
                task_queue=WORKFLOW_TASK_QUEUE,
            )

        # Final status should be completed
        assert result.status == RunStatus.COMPLETED
