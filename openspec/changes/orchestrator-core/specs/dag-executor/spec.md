# Capability: dag-executor

## Purpose

Execute the three-phase agent DAG as a Temporal workflow, dispatching 11 agents as Temporal activities and gating each phase transition on completion-register confirmation that all expected agents have emitted terminal status to their Redis Streams. Implemented as the `ClaimVerificationWorkflow` per ADR-0016.

## Behaviour

### Phase definitions

| Phase | ID | Mode       | Agents | Run Status |
|-------|----|------------|--------|------------|
| Ingestion  | 1 | sequential | ingestion-agent, claim-detector, entity-extractor | `ingesting` |
| Fan-out (evidence)   | 2a | parallel   | claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence | `analyzing` |
| Fan-out (validation) | 2b | sequential | source-validator | `analyzing` |
| Synthesis  | 3 | sequential | blindspot-detector, synthesizer | `synthesizing` |

### Sequential phase execution (Phases 1, 3)

For each agent in the phase list, in order:
1. Call `workflow.execute_activity(run_agent_activity, args=[agent_name, input], ...)`.
2. The activity internally invokes the agent's LangChain logic, which publishes START/OBS/STOP to `reasoning:{runId}:{agent}`.
3. The activity returns `AgentActivityResult` with `terminal_status` (F or X) and `observation_count`.
4. The workflow updates the completion register with the returned terminal status.
5. Proceed to the next agent in the list.

Special case -- **check-worthiness gate** (claim-detector in Phase 1):
- If claim-detector returns `terminal_status = "X"` (score < 0.4), the workflow calls `cancel_run` activity and returns early. No further agents are dispatched.

### Parallel phase execution (Phase 2a)

1. Dispatch five evidence-gathering agents simultaneously using `asyncio.gather()` over five `workflow.execute_activity()` calls: claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence.
2. Each activity follows the same invocation + stream lifecycle as sequential dispatch.
3. `asyncio.gather()` resolves when all five activities complete.
4. The workflow updates the completion register for all five agents.
5. Proceed to Phase 2b.

### Sequential phase execution (Phase 2b)

1. After Phase 2a completes, the orchestrator reads URL-related observations from all Phase 2a agents' streams and prepares `cross_agent_data` for the source-validator.
2. Dispatch source-validator via `workflow.execute_activity(run_agent_activity, args=["source-validator", input], ...)`.
3. The source-validator receives complete cross-agent data because all evidence-gathering agents have already emitted STOP.
4. The workflow updates the completion register for source-validator.
5. Proceed to Phase 3.

### Phase transition gates

Before advancing from Phase N to Phase N+1:
- The workflow calls `update_run_status` activity to transition run status (e.g., `ingesting` -> `analyzing`).
- `CompletionRegister.is_phase_complete(phase)` must return `True`.
- If an activity fails after Temporal retries are exhausted, the workflow catches `ActivityError`, calls `fail_run` activity, and terminates.

### Temporal activity configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `start_to_close_timeout` | 120 s | NFR-001 budget per agent |
| `heartbeat_timeout` | 60 s | NFR-025 agent heartbeat monitoring |
| `retry_policy.initial_interval` | 1 s | Backoff for transient LLM errors |
| `retry_policy.backoff_coefficient` | 2.0 | Exponential backoff |
| `retry_policy.maximum_interval` | 30 s | Cap backoff |
| `retry_policy.maximum_attempts` | 3 | Three attempts before failure |
| `retry_policy.non_retryable_error_types` | `InvalidClaimError`, `MissingApiKeyError` | Configuration errors fail immediately |
| Task queue | `agent-task-queue` | Shared queue for all agent workers |

### Error handling

| Condition | Action |
|-----------|--------|
| Agent activity fails after max retries | Workflow catches `ActivityError`, calls `fail_run` activity, returns `WorkflowResult` with `failed` status |
| Agent emits STOP with status X (cancelled) | Activity returns `terminal_status="X"`. Workflow records in register. For claim-detector: cancels run. For other agents: phase still advances if all agents have terminal status. |
| Temporal worker crashes mid-execution | Temporal replays workflow from event history. Activities that completed successfully are not re-executed. In-progress activities are retried. |
| `asyncio.gather` raises (unexpected exception) | Workflow catches, calls `fail_run`, terminates |

### Recovery on workflow replay

When the Temporal worker restarts:
1. Temporal replays the workflow from its event history.
2. Activities that previously completed return their recorded results (no re-execution).
3. The workflow optionally calls `rebuild_completion_register` activity to verify consistency with Redis Streams.
4. The DAG executor resumes from the point of failure.

### Interface

```python
@dataclass
class Phase:
    id: int
    name: str
    agents: list[str]
    mode: Literal["sequential", "parallel"]

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
    verdict_id: str | None
    agent_results: dict[str, str]  # agent_name -> terminal_status

@workflow.defn
class ClaimVerificationWorkflow:
    @workflow.run
    async def run(self, input: WorkflowInput) -> WorkflowResult:
        """Execute all phases in DAG order. Updates run status via activities."""
```

## Acceptance criteria

- Phase 1 dispatches ingestion-agent, claim-detector, entity-extractor serially; each agent's STOP is confirmed via activity return before the next agent is dispatched.
- Phase 2a dispatches five evidence-gathering agents simultaneously; `asyncio.gather()` waits for all five to complete.
- Phase 2b dispatches source-validator after Phase 2a completes; source-validator receives complete cross-agent data.
- Phase 3 dispatches blindspot-detector then synthesizer serially.
- Phase N+1 does not start until all agents in Phase N have terminal status in the completion register.
- Check-worthiness gate: claim-detector returning `terminal_status="X"` causes the run to be cancelled without dispatching further agents.
- An agent emitting STOP with status X (other than claim-detector) does not block phase completion if all other phase agents also have terminal status.
- Activity failure after max Temporal retries transitions run to `failed`.
- Temporal workflow replay after worker restart does not re-execute completed activities.
- Run status transitions follow: `pending` -> `ingesting` -> `analyzing` -> `synthesizing` -> `completed`.
- End-to-end run with stub agents completes within the 120 s NFR-001 budget in integration tests.
- Progress events are published to `progress:{runId}` at each agent start, agent completion, and phase transition.
