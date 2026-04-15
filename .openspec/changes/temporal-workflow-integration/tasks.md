## 1. Temporal Infrastructure

- [x] 1.1 Add Temporal server service to docker-compose.yml (temporalio/auto-setup image)
- [x] 1.2 Add Temporal UI service to docker-compose.yml (temporalio/ui, port 8233)
- [x] 1.3 Add Temporal database service (PostgreSQL for Temporal persistence)
- [x] 1.4 Configure Temporal namespace `swarm-reasoning` in auto-setup
- [x] 1.5 Add health checks for Temporal server in docker-compose
- [x] 1.6 Document Temporal UI access at http://localhost:8233

## 2. Activity Contracts

- [x] 2.1 Define `AgentActivityInput` dataclass: runId, claimText, sourceUrl, sourceDate, agentName, phase
- [x] 2.2 Define `AgentActivityOutput` dataclass: agentName, terminalStatus (F/X), observationCount, durationMs
- [x] 2.3 Define activity interface for `run_agent_activity(input: AgentActivityInput) -> AgentActivityOutput`
- [x] 2.4 Implement base activity function that wraps the agent session protocol (START -> OBS -> STOP)
- [x] 2.5 Register activity for ingestion-agent with task queue `agent:ingestion-agent`
- [x] 2.6 Register activity for claim-detector with task queue `agent:claim-detector`
- [x] 2.7 Register activity for entity-extractor with task queue `agent:entity-extractor`
- [x] 2.8 Register activity for claimreview-matcher with task queue `agent:claimreview-matcher`
- [x] 2.9 Register activity for coverage-left with task queue `agent:coverage-left`
- [x] 2.10 Register activity for coverage-center with task queue `agent:coverage-center`
- [x] 2.11 Register activity for coverage-right with task queue `agent:coverage-right`
- [x] 2.12 Register activity for domain-evidence with task queue `agent:domain-evidence`
- [x] 2.13 Register activity for source-validator with task queue `agent:source-validator`
- [x] 2.14 Register activity for blindspot-detector with task queue `agent:blindspot-detector`
- [x] 2.15 Register activity for synthesizer with task queue `agent:synthesizer`

## 3. Workflow Definition

- [x] 3.1 Implement `ClaimVerificationWorkflow` class with `@workflow.defn` decorator
- [x] 3.2 Implement workflow input: runId, sessionId, claimText, sourceUrl, sourceDate
- [x] 3.3 Implement Phase 1 execution: sequential ingestion-agent -> claim-detector -> entity-extractor
- [x] 3.4 Implement check-worthiness gate: if claim-detector score < 0.4, cancel run and skip Phases 2-3
- [x] 3.5 Implement Phase 2 execution: parallel fan-out of 6 activities using asyncio.gather
- [x] 3.6 Implement Phase 3 execution: sequential blindspot-detector -> synthesizer
- [x] 3.7 Implement run status updates: pending -> ingesting -> analyzing -> synthesizing -> completed
- [x] 3.8 Publish run status changes to progress:{runId} stream for SSE relay
- [x] 3.9 Implement workflow_completed signal on successful completion
- [x] 3.10 Implement workflow_failed signal on unrecoverable failure
- [x] 3.11 Implement run cancellation flow (status -> cancelled) for check-worthiness gate
- [x] 3.12 Implement error handling: catch activity failures, transition run to `failed` after retry exhaustion

## 4. Retry Policies and Timeouts

- [x] 4.1 Define Phase 1 retry policy: max_attempts=3, initial_interval=5s, backoff_coefficient=2.0, max_interval=30s
- [x] 4.2 Define Phase 2 retry policy: same as Phase 1
- [x] 4.3 Define Phase 3 retry policy: same as Phase 1
- [x] 4.4 Define non-retryable error types: InvalidClaimError, MissingApiKeyError, SchemaValidationError
- [x] 4.5 Set Phase 1 activity timeout: start_to_close=30s, schedule_to_close=60s
- [x] 4.6 Set Phase 2 activity timeout: start_to_close=45s, schedule_to_close=90s
- [x] 4.7 Set Phase 3 activity timeout: start_to_close=60s, schedule_to_close=120s

## 5. Worker Configuration

- [x] 5.1 Install `temporalio` Python SDK in agent-service dependencies
- [x] 5.2 Implement worker entry point in `agent_service/worker.py`
- [x] 5.3 Create Temporal client connection configuration (TEMPORAL_ADDRESS env var)
- [x] 5.4 Register all 11 agent activities with their respective task queues
- [x] 5.5 Configure worker concurrency: max_concurrent_activities=1 per worker (agents are stateless but LLM-bound)
- [x] 5.6 Implement graceful shutdown: drain in-progress activities before exit
- [x] 5.7 Implement worker health check endpoint for docker-compose
- [x] 5.8 Configure workflow worker for `claim-verification` task queue (runs the workflow itself)

## 6. NestJS Temporal Client

- [x] 6.1 Install `@temporalio/client` in NestJS backend dependencies
- [x] 6.2 Implement TemporalClientAdapter.startClaimVerificationWorkflow(runId, sessionId, claimText, sourceUrl, sourceDate)
- [x] 6.3 Generate workflow ID from runId for idempotency
- [x] 6.4 Implement TemporalClientAdapter.getWorkflowStatus(workflowId) for health check
- [ ] 6.5 Implement completion signal handler in NestJS to trigger FinalizeSessionUseCase

## 7. Tests

- [x] 7.1 Unit test: ClaimVerificationWorkflow phase sequencing (Phase 1 before 2 before 3)
- [x] 7.2 Unit test: Phase 2 parallel execution (all 6 activities dispatched concurrently)
- [x] 7.3 Unit test: Check-worthiness gate cancels run when score < 0.4
- [x] 7.4 Unit test: Retry policy applied on transient failure
- [x] 7.5 Unit test: Non-retryable error fails immediately without retry
- [x] 7.6 Unit test: Activity timeout triggers failure after elapsed time
- [x] 7.7 Unit test: Run status transitions at each phase boundary
- [x] 7.8 Integration test: Workflow execution with mocked agent activities (Temporal test server)
- [x] 7.9 Integration test: Worker registration and activity discovery
- [x] 7.10 Integration test: NestJS TemporalClientAdapter starts workflow and receives completion
