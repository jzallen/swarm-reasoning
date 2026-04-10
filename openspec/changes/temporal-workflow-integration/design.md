## Context

Temporal.io replaces MCP as the control plane (ADR-016). The orchestrator is a Temporal workflow that coordinates 11 agents across three phases. Each agent is a Temporal activity executed by a dedicated Python worker. The NestJS backend starts workflows via the Temporal client and receives completion signals. The Redis Streams data plane (ADR-012) is unchanged -- agents still publish observations to their streams.

Key constraints from ADRs:
- ADR-016: Temporal replaces MCP; workflow survives crashes via event history replay
- ADR-014: Three-service architecture; agent service runs Temporal workers
- ADR-012: Redis Streams data plane unchanged
- ADR-013: Two communication planes (Temporal control, Redis data) fail independently

## Scope Boundary

This slice owns the **Temporal SDK infrastructure**: worker setup, task queue configuration, Temporal client adapter for NestJS, retry policies, activity timeouts, and activity interface contracts. The workflow **business logic** (DAG phases, completion register, run lifecycle state machine) is owned by the `orchestrator-core` slice. This slice provides the Temporal primitives; orchestrator-core composes them into the claim verification workflow.

## Goals / Non-Goals

**Goals:**
- ClaimVerificationWorkflow implementing the three-phase DAG
- Activity interfaces for all 11 agents with retry policies and timeouts
- Temporal worker configuration in the Python agent service
- Task queue design for independent agent scaling
- Workflow signals for backend notification on completion
- Run status updates at phase transitions (pending -> ingesting -> analyzing -> synthesizing -> completed)
- Cancellation support (check-worthiness gate in Phase 1 can cancel the run)

**Non-Goals:**
- LangChain agent logic (separate per-agent slices)
- Redis Streams observation publishing (covered by redis-streams-observation-schema slice)
- NestJS backend endpoints (covered by nestjs-backend-core slice)
- Temporal server deployment/configuration (infrastructure concern)
- Kafka graduation (ADR-012 defers to production)

## Decisions

### 1. One task queue per agent type
Each agent type gets its own task queue (e.g., `agent:ingestion-agent`, `agent:claim-detector`). This allows independent scaling -- a slow agent type can have more workers without affecting others. The workflow dispatches activities to the correct queue.

**Alternative considered:** Single shared queue. Rejected -- a slow agent blocks others; no independent scaling.

### 2. Three-phase DAG as workflow logic
Phase 1 runs three activities sequentially (ingestion-agent, claim-detector, entity-extractor). Phase 2a runs five activities in parallel (claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence). Phase 2b runs source-validator sequentially after 2a completes (it needs cross-agent observation data from 2a). Phase 3 runs two activities sequentially (blindspot-detector, synthesizer). Temporal's `workflow.execute_activity` and `asyncio.gather` express this naturally.

**Alternative considered:** Child workflows per phase. Rejected -- adds complexity without benefit; single workflow is simpler to monitor.

### 3. Typed activity input/output contracts
Each activity receives `AgentActivityInput` (runId, claimText, sourceUrl, sourceDate, agentName, phase) and returns `AgentActivityOutput` (agentName, terminalStatus, observationCount, durationMs). This standardized contract keeps the workflow logic generic.

### 4. Retry policy: 3 retries with exponential backoff
Activities retry up to 3 times for transient failures (LLM rate limits, API timeouts, network errors). Initial interval: 5s, backoff coefficient: 2.0, max interval: 30s. Non-retryable errors (invalid claim, missing API key) are listed in `non_retryable_error_types`.

### 5. Phase-specific activity timeouts
Phase 1 (ingestion): 30s start-to-close timeout. Phase 2 (fan-out): 45s -- external API calls may be slower. Phase 3 (synthesis): 60s -- synthesizer reads all streams and produces the verdict. Schedule-to-close timeout is 2x the start-to-close timeout.

### 6. Workflow signals for backend notification
The workflow emits a `workflow_completed` signal when all phases finish successfully, or a `workflow_failed` signal on unrecoverable failure. The NestJS backend's TemporalClientAdapter listens for these signals to trigger FinalizeSessionUseCase.

### 7. Check-worthiness gate cancels run
If the claim-detector activity returns a check-worthiness score below 0.4, the workflow transitions the run to `cancelled` and skips Phases 2 and 3. The workflow emits a `workflow_completed` signal with the cancellation status.

## Risks / Trade-offs

- **[Temporal server as infrastructure dependency]** -- Adds operational complexity. Mitigated by docker-compose for dev and Temporal Cloud option for prod.
- **[Activity timeout tuning]** -- Timeouts may need adjustment based on actual LLM latency. Starting conservative; observable via Temporal UI.
- **[Single workflow per claim]** -- If a claim triggers very long-running agents, the workflow history grows. Acceptable at current scale (<100 activities per workflow).
- **[Python SDK maturity]** -- Temporal Python SDK is stable but younger than the Go/Java SDKs. Well-maintained with active community.
