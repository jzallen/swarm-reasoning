## Context

Slice 1 delivers typed observation models and the `ReasoningStream` ABC with a Redis backend. The orchestrator builds on those foundations. It never writes observations -- that is agent work -- but it reads agent streams continuously via `XREADGROUP`, dispatches agents as Temporal activities, and decides when each phase is complete.

Key constraints from ADRs:
- **ADR-0016**: Temporal.io replaces MCP as the control plane. The orchestrator IS a Temporal workflow (`ClaimVerificationWorkflow`). Each agent is a Temporal activity worker. Supersedes ADR-0009 and ADR-0010.
- **ADR-0013**: Two planes -- Temporal control plane + Redis Streams data plane, fail independently
- **NFR-001**: End-to-end run latency <= 120 seconds
- **NFR-003**: Temporal activity dispatch latency P99 < 2000 ms
- **NFR-005**: Agent idempotency -- orchestrator may safely re-invoke an agent that already started; the agent must handle duplicate START
- **NFR-007**: Orchestrator restart recovery without data loss (Temporal event history replay)
- **NFR-025**: Agent heartbeat monitoring -- detect unresponsive agents within 30 seconds

Run states from `docs/domain/entities/run.md`: `pending`, `ingesting`, `analyzing`, `synthesizing`, `completed`, `cancelled`, `failed`.

## Scope Boundary

This slice owns the **workflow business logic**: the three-phase DAG, agent dispatch ordering, completion register, and run lifecycle state machine. The **Temporal SDK infrastructure** (worker setup, task queues, retry policies, activity interface contracts, client adapter) is owned by the `temporal-workflow-integration` slice. This slice depends on temporal-workflow-integration for Temporal primitives and composes them into the `ClaimVerificationWorkflow`.

## Goals / Non-Goals

**Goals:**
- Implement the three-phase execution DAG as a Temporal workflow with correct sequential/parallel ordering across 11 agents
- Gate phase transitions on Redis Streams STOP signals verified within the Temporal workflow
- Survive orchestrator crashes via Temporal event history replay (NFR-007)
- Monitor agent heartbeats via Temporal activity heartbeats and stream-activity polling (NFR-025)
- Persist run status to PostgreSQL so the NestJS backend can query it without coupling to the workflow process
- Keep the workflow deterministic -- all non-deterministic I/O happens inside activities

**Non-Goals:**
- Agent implementation (separate slices)
- NestJS backend API (separate slice)
- Kafka transport graduation (ADR-0012 defers this)
- Horizontal scaling of workflow workers (single worker; DAG is not distributed)
- Health endpoint (owned by the NestJS backend, not the Python agent service)
- Result storage beyond run status -- observations live in Redis Streams (slice 1)

## Decisions

### 1. Phase-gating via Redis Streams STOP scan within Temporal activities

The workflow dispatches an agent by calling a Temporal activity. That activity invokes the agent's LangChain logic and waits for the agent to publish a STOP message to its Redis Stream. The completion register (running inside a helper activity or within the workflow) confirms all expected agents for the current phase have emitted STOP. The workflow does not proceed to the next phase until gating is satisfied.

This preserves the two-plane independence from ADR-0013: Temporal manages execution flow; Redis Streams remain the authoritative data plane for agent output.

**Alternative considered:** Gate on Temporal activity return values only. Rejected -- the Redis Streams STOP message is the authoritative signal per ADR-003; relying only on activity return values would create a second source of truth.

### 2. Completion register: in-memory dict within workflow, rebuilt on replay

```python
# register[agent_name] = terminal_status ("F" | "X") | None
register: dict[str, str | None]
```

On Temporal workflow replay, the register is reconstructed from the replayed activity results. For explicit recovery (e.g., after a worker crash), a `rebuild_completion_register` activity scans Redis Streams via `XRANGE reasoning:{runId}:{agent} - +` for each agent and returns the completion state. The workflow merges this into its register.

Cost: one XRANGE per agent per recovery. At 11 agents and infrequent restarts, this is acceptable (NFR-007).

**Alternative considered:** Persist completion register to a separate PostgreSQL table. Rejected -- adds a second source of truth. STOP messages in Redis Streams are already authoritative. Temporal event history provides implicit persistence.

### 3. Three-phase DAG as a static data structure

```python
DAG: list[Phase] = [
    Phase(id=1, name="ingestion", agents=[
        "ingestion-agent",
        "claim-detector",
        "entity-extractor",
    ], mode="sequential"),
    Phase(id="2a", name="fanout", agents=[
        "claimreview-matcher",
        "coverage-left",
        "coverage-center",
        "coverage-right",
        "domain-evidence",
    ], mode="parallel"),
    Phase(id="2b", name="fanout-validation", agents=[
        "source-validator",
    ], mode="sequential"),
    Phase(id=3, name="synthesis", agents=[
        "blindspot-detector",
        "synthesizer",
    ], mode="sequential"),
]
```

Phase 1 dispatches three agents sequentially via `await activity()`. Phase 2a dispatches five evidence-gathering agents concurrently via `asyncio.gather()`. Phase 2b dispatches source-validator after Phase 2a completes, so it receives complete cross-agent data (URLs from all evidence-gathering agents). Phase 3 dispatches two agents sequentially.

**Alternative considered:** Six agents in a single parallel Phase 2 batch. Rejected -- the source-validator needs URLs from the other Phase 2 agents (coverage-left, coverage-center, coverage-right, claimreview-matcher, domain-evidence). Dispatching it in parallel means the orchestrator cannot provide complete cross-agent data at dispatch time, resulting in incomplete citation lists and inaccurate convergence scores.

**Alternative considered:** Five-phase DAG (splitting ingestion from sequential and blindspot from synthesis). Rejected -- the domain model uses three phases (`ingestion`, `fanout`, `synthesis`) matching the run state transitions (`ingesting`, `analyzing`, `synthesizing`). The 2a/2b split is internal to the fanout phase and does not introduce a new run status.

### 4. Temporal workflow and activity structure

```python
@workflow.defn
class ClaimVerificationWorkflow:
    """Orchestrates the three-phase agent pipeline as a Temporal workflow."""

    @workflow.run
    async def run(self, input: WorkflowInput) -> WorkflowResult:
        # Phase 1 -- Sequential ingestion
        await workflow.execute_activity(
            run_agent_activity, args=["ingestion-agent", input], ...)
        await workflow.execute_activity(
            run_agent_activity, args=["claim-detector", input], ...)
        await workflow.execute_activity(
            run_agent_activity, args=["entity-extractor", input], ...)

        # Phase 2a -- Parallel fan-out (5 evidence-gathering agents)
        await asyncio.gather(
            workflow.execute_activity(run_agent_activity, args=["claimreview-matcher", input], ...),
            workflow.execute_activity(run_agent_activity, args=["coverage-left", input], ...),
            workflow.execute_activity(run_agent_activity, args=["coverage-center", input], ...),
            workflow.execute_activity(run_agent_activity, args=["coverage-right", input], ...),
            workflow.execute_activity(run_agent_activity, args=["domain-evidence", input], ...),
        )

        # Phase 2b -- Source validation (after 2a completes, receives complete cross-agent data)
        await workflow.execute_activity(
            run_agent_activity, args=["source-validator", input], ...)

        # Phase 3 -- Sequential synthesis
        await workflow.execute_activity(
            run_agent_activity, args=["blindspot-detector", input], ...)
        await workflow.execute_activity(
            run_agent_activity, args=["synthesizer", input], ...)
```

Each `run_agent_activity` is a Temporal activity that:
1. Invokes the agent's LangChain logic
2. Publishes START to `reasoning:{runId}:{agent}`
3. Executes agent tools (which publish observations to Redis Streams)
4. Publishes STOP to `reasoning:{runId}:{agent}`
5. Returns the agent's terminal status (F or X) and observation count

**Alternative considered:** One Temporal activity per agent type with separate activity functions. Rejected for now -- a single `run_agent_activity` with agent name parameter reduces boilerplate. Agent-specific logic is in the agent modules, not the activity.

### 5. Run status persisted to PostgreSQL

Run status is persisted to PostgreSQL via TypeORM (the NestJS backend's ORM). The Temporal workflow updates run status by calling a `update_run_status` activity that writes to PostgreSQL.

```
pending -> ingesting       (workflow starts Phase 1)
ingesting -> analyzing     (Phase 1 complete, Phase 2 starts)
analyzing -> synthesizing  (Phase 2 complete, Phase 3 starts)
synthesizing -> completed  (Phase 3 complete, verdict extracted)
{any} -> cancelled         (check-worthiness gate rejects claim)
{any} -> failed            (unrecoverable error)
```

The NestJS backend queries PostgreSQL directly for run status. No orchestrator process needs to be running for a status query. This decouples the query path from the Temporal workflow.

**Alternative considered:** Store run status in Redis hash. Rejected -- PostgreSQL is the system of record for domain entities (ADR-0017); run status belongs with claims, sessions, and verdicts.

### 6. Heartbeat monitoring via Temporal activity heartbeats

Temporal activities support heartbeating. Each `run_agent_activity` heartbeats periodically (every 10 seconds) by reading the agent's stream for recent activity. If the agent has not published any message for > 30 seconds (configurable), the activity reports unhealthy. Temporal's `heartbeat_timeout` on the activity (default: 60 seconds) will cancel the activity if heartbeats stop, which the workflow catches and transitions the run to `failed`.

Additionally, the workflow uses Redis Streams `XREVRANGE ... COUNT 1` within the activity to detect silent agents. This satisfies NFR-025 without requiring agents to implement an explicit heartbeat mechanism.

### 7. Package structure

```
services/
  agent-service/
    src/
      workflows/
        __init__.py
        claim_verification.py  -- ClaimVerificationWorkflow, WorkflowInput, WorkflowResult
        dag.py                 -- Phase dataclass, DAG definition
      activities/
        __init__.py
        run_agent.py           -- run_agent_activity: dispatches agent logic, manages stream lifecycle
        completion.py          -- rebuild_completion_register activity: XRANGE scan for STOP messages
        run_status.py          -- update_run_status activity: writes to PostgreSQL
      completion/
        __init__.py
        register.py            -- CompletionRegister: in-memory register, mark_complete, is_phase_complete
      worker.py                -- Temporal worker entrypoint: registers workflow + activities
    tests/
      unit/
        test_dag.py
        test_completion.py
        test_workflow.py       -- Temporal workflow sandbox tests
      integration/
        test_orchestrator_run.py    -- Full run with stub agent activities
        test_restart_recovery.py    -- Kill and restart worker, verify Temporal replays correctly
```

## Risks / Trade-offs

- **[Temporal server dependency]** -- Adds an infrastructure component. Mitigated by using Temporal's docker image in dev and Temporal Cloud for production. If Temporal is unavailable, no new runs can start, but existing Redis Streams data is preserved.
- **[asyncio.gather for Phase 2a]** -- If one fan-out agent activity hangs, the Phase 2a gate blocks until Temporal's activity timeout fires. Heartbeat monitoring within the activity detects and cancels after 60 seconds. Acceptable for prototype; production can tune timeouts.
- **[Temporal SDK learning curve]** -- Team must learn workflow/activity/worker concepts. Mitigated by the Temporal UI for debugging and clear separation of workflow (deterministic) vs. activity (side effects).
- **[NFR-001: 120 s latency]** -- The four sequential steps (Phase 1, 2a, 2b, 3) add orchestration overhead. Temporal dispatch latency (NFR-003) must stay under 2 seconds P99. Parallel Phase 2a amortizes five fan-out agents. Phase 2b adds one sequential agent (source-validator) but ensures complete cross-agent data.
- **[Workflow determinism]** -- Temporal workflows must be deterministic. All I/O (Redis reads, PostgreSQL writes, LLM calls) happens inside activities. The workflow only dispatches activities and reads their results.
