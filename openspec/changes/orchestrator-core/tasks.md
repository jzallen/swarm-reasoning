## Prerequisites

- [ ] Slice 1 (types/stream) is complete: `swarm_reasoning.models`, `swarm_reasoning.stream.redis` are importable
- [ ] Temporal server is running (docker-compose includes `temporal` service)
- [ ] PostgreSQL is running with `runs` table migrated (TypeORM entity from NestJS backend)

---

## 1. Project Setup

- [ ] 1.1 Create directory structure: `services/agent-service/src/workflows/`, `services/agent-service/src/activities/`, `services/agent-service/src/completion/` with `__init__.py` files
- [ ] 1.2 Add `temporalio>=1.4.0`, `asyncpg>=0.29`, `sqlalchemy[asyncio]>=2.0` to `pyproject.toml` dependencies
- [ ] 1.3 Create test directory structure: `services/agent-service/tests/unit/`, `services/agent-service/tests/integration/`
- [ ] 1.4 Add Temporal server service to `docs/infrastructure/docker-compose.yml` with health check
- [ ] 1.5 Add `TEMPORAL_HOST`, `TEMPORAL_NAMESPACE` environment variables to `.env.example`; define `agent-task-queue` constant

---

## 2. DAG Definition

- [ ] 2.1 Define `Phase` dataclass in `workflows/dag.py` with fields: `id`, `name`, `agents`, `mode`
- [ ] 2.2 Define DAG constant: Phase 1 ingestion (3 agents, sequential), Phase 2 fanout (6 agents including source-validator, parallel), Phase 3 synthesis (2 agents, sequential) -- total 11 agents
- [ ] 2.3 Write unit tests: agent count = 11, phase modes correct, no duplicate agents, source-validator in Phase 2

---

## 3. Workflow Input/Output Models

- [ ] 3.1 Define `WorkflowInput` dataclass: `run_id`, `claim_id`, `session_id`, `claim_text`
- [ ] 3.2 Define `WorkflowResult` dataclass: `run_id`, `final_status`, `verdict_id`, `agent_results`
- [ ] 3.3 Define `AgentActivityInput` and `AgentActivityResult` dataclasses with agent name, terminal status, observation count, duration

---

## 4. Run Lifecycle (PostgreSQL Persistence)

- [ ] 4.1 Define `RunStatusEnum` with values: `pending`, `ingesting`, `analyzing`, `synthesizing`, `completed`, `cancelled`, `failed`
- [ ] 4.2 Implement valid transition map and `InvalidRunTransition` exception
- [ ] 4.3 Implement `update_run_status` Temporal activity: validate transition, write to PostgreSQL via async SQLAlchemy
- [ ] 4.4 Implement `cancel_run` activity: transition to `cancelled` with reason; no-op if already terminal
- [ ] 4.5 Implement `fail_run` activity: transition to `failed` with error message; no-op if already terminal
- [ ] 4.6 Implement `get_run_status` activity: read current status from PostgreSQL
- [ ] 4.7 Write unit tests: valid transitions, invalid transitions raise exception, cancel/fail no-op on terminal states

---

## 5. Completion Register

- [ ] 5.1 Implement `CompletionRegister` class with `_register: dict[str, str | None]` in `completion/register.py`
- [ ] 5.2 Implement `register_agent()`, `mark_complete()` (idempotent), `is_phase_complete()`, `is_agent_complete()`, `get_status()`, `get_incomplete_agents()`
- [ ] 5.3 Implement `reset()` to clear all state
- [ ] 5.4 Implement `rebuild_completion_register` Temporal activity: XRANGE each agent stream for STOP messages, return dict of agent->status
- [ ] 5.5 Implement `merge_from_rebuild()` to integrate rebuild results
- [ ] 5.6 Write unit tests: phase complete logic, idempotent mark_complete, reset, rebuild with mocked Redis

---

## 6. Agent Activity (run_agent_activity)

- [ ] 6.1 Implement `run_agent_activity` in `activities/run_agent.py`: look up agent handler by name, invoke `handler.run()`, return `AgentActivityResult`
- [ ] 6.2 Implement stream lifecycle: verify START published before agent logic, verify STOP after
- [ ] 6.3 Implement activity heartbeating every 10 seconds with stream-activity health check via `XREVRANGE`
- [ ] 6.4 Implement progress event publishing to `progress:{runId}` at agent start and completion
- [ ] 6.5 Implement error classification: LLM rate limits/timeouts retryable; auth/config errors non-retryable
- [ ] 6.6 Write unit tests: heartbeat calls, error classification, result construction

---

## 7. Temporal Retry Policy

- [ ] 7.1 Define default retry policy: `initial_interval=1s`, `backoff_coefficient=2.0`, `maximum_interval=30s`, `maximum_attempts=3`
- [ ] 7.2 Define non-retryable error types: `InvalidClaimError`, `MissingApiKeyError`, `StreamNotFoundError`
- [ ] 7.3 Configure activity timeouts: `start_to_close_timeout=120s`, `heartbeat_timeout=60s`, `schedule_to_close_timeout=300s`

---

## 8. ClaimVerificationWorkflow

- [ ] 8.1 Implement workflow class with `@workflow.defn` decorator, `@workflow.run` method accepting `WorkflowInput`
- [ ] 8.2 Implement Phase 1 sequential dispatch: `await workflow.execute_activity()` for ingestion-agent, claim-detector, entity-extractor
- [ ] 8.3 Implement check-worthiness gate: if claim-detector returns `terminal_status="X"`, call `cancel_run` and return early
- [ ] 8.4 Implement Phase 1->2 transition: call `update_run_status` to transition `ingesting -> analyzing`
- [ ] 8.5 Implement Phase 2 parallel dispatch: `asyncio.gather()` over six `workflow.execute_activity()` calls
- [ ] 8.6 Implement Phase 2->3 transition: call `update_run_status` to transition `analyzing -> synthesizing`
- [ ] 8.7 Implement Phase 3 sequential dispatch for blindspot-detector, synthesizer
- [ ] 8.8 Implement Phase 3 completion: transition `synthesizing -> completed`
- [ ] 8.9 Implement error handling: catch `ActivityError`, call `fail_run`, return failed `WorkflowResult`
- [ ] 8.10 Implement completion register integration: merge activity results into register after each activity
- [ ] 8.11 Implement recovery path: call `rebuild_completion_register` on workflow start to detect already-completed agents
- [ ] 8.12 Write workflow sandbox unit tests: sequential ordering, parallel dispatch, check-worthiness gate

---

## 9. Heartbeat Monitoring

- [ ] 9.1 Implement heartbeat check within `run_agent_activity`: periodic `XREVRANGE` on agent stream
- [ ] 9.2 Configure heartbeat interval (10s) and warning threshold (30s) as constants
- [ ] 9.3 Integrate with `activity.heartbeat()`: pass latest stream timestamp as details
- [ ] 9.4 Write unit tests: heartbeat timing, warning threshold detection

---

## 10. Temporal Worker Entrypoint

- [ ] 10.1 Implement `worker.py`: register workflow and all activities, listen on `agent-task-queue`
- [ ] 10.2 Implement graceful shutdown on SIGTERM: stop accepting new workflows, wait for in-progress activities
- [ ] 10.3 Wire dependencies: Redis client, PostgreSQL connection, Anthropic client
- [ ] 10.4 Add worker startup to docker-compose agent-service entrypoint

---

## 11. Consumer Group Setup

- [ ] 11.1 Implement `setup_consumer_groups` utility: idempotent `XGROUP CREATE` on each agent stream at worker startup
- [ ] 11.2 Write unit test: consumer group creation handles BUSYGROUP error

---

## 12. Progress Events

- [ ] 12.1 Define progress event format: agent, phase, status, message, timestamp
- [ ] 12.2 Implement `publish_progress` helper: XADD to `progress:{runId}` at agent start/completion and phase transitions
- [ ] 12.3 Write unit test: progress event format and content

---

## 13. Integration Tests

- [ ] 13.1 Write stub agent handler fixture: publishes START/OBS/STOP, returns AgentActivityResult
- [ ] 13.2 Full run with 11 stub agents: verify `completed` status, all streams contain START+STOP
- [ ] 13.3 Check-worthiness gate: claim-detector returns X, verify `cancelled`, no Phase 2 agents dispatched
- [ ] 13.4 Worker restart: kill mid-Phase-2, restart, verify Temporal replays and completes
- [ ] 13.5 Phase 2 parallel: verify all 6 agents start within 2 seconds of each other
- [ ] 13.6 Heartbeat timeout: stub agent never STOPs, verify activity cancelled by heartbeat_timeout
- [ ] 13.7 Activity retry: transient error on first attempt, success on second
- [ ] 13.8 Non-retryable error: auth error fails immediately, run transitions to `failed`
- [ ] 13.9 Completion register rebuild: partially complete run, verify rebuild identifies completed agents
- [ ] 13.10 Progress events: verify `progress:{runId}` contains events for each agent and phase transition
- [ ] 13.11 End-to-end latency: full run with stubs completes within 15 seconds
- [ ] 13.12 Run status transitions: verify PostgreSQL records correct status at each phase boundary

---

## Completion Definition

All tasks above are checked. Unit tests pass. Integration tests pass with Temporal test environment and stub agents. `ClaimVerificationWorkflow` dispatches 11 agents across 3 phases. Run status transitions match `docs/domain/entities/run.md`. Heartbeat monitoring detects unresponsive agents within 60 seconds. Completion register rebuilds from Redis Streams STOP messages.
