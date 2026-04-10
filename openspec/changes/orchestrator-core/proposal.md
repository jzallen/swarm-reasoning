## Why

Slice 1 (redis-streams-observation-schema) established the wire format and transport interface. Without an orchestrator, no agent is ever invoked, no observations flow, and no verdicts are produced. The orchestrator is the control-plane hub that sequences the 11 agents across three phases, tracks completion, and drives run status from `pending` through to `completed` or `failed`. This slice must come before any agent implementation because it defines the DAG contract every agent must satisfy and the run lifecycle every consumer depends on.

## What Changes

- Implement the `ClaimVerificationWorkflow` as a Temporal workflow: the five-phase execution DAG dispatching 11 agents as Temporal activities across three phases (sequential ingestion, parallel fan-out, sequential synthesis) per ADR-0016
- Implement the `CompletionRegister`: per-run, per-agent bookkeeping rebuilt from Redis Streams STOP messages on workflow replay (NFR-007)
- Implement the run lifecycle state machine: `pending` -> `ingesting` -> `analyzing` -> `synthesizing` -> `completed` | `cancelled` | `failed`, with state persisted to PostgreSQL via TypeORM and transitions driven by the Temporal workflow
- Implement heartbeat monitoring via Temporal activity heartbeats and Redis Streams stream-activity polling (NFR-025)
- Define Temporal activity stubs, retry policies, and task queue configuration for all 11 agents

## Capabilities

### New Capabilities

- `dag-executor`: Five-phase DAG execution implemented as a Temporal workflow. Phase 1 (sequential): ingestion-agent, claim-detector, entity-extractor dispatched as sequential `await activity()` calls. Phase 2 (parallel): claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence, source-validator dispatched via `asyncio.gather()` over activity calls (6 agents). Phase 3 (sequential): blindspot-detector, synthesizer dispatched sequentially. Gates each phase transition on completion-register confirmation that all expected agents have emitted terminal STOP status.
- `completion-register`: Ephemeral per-run bookkeeping tracking which agents have emitted STOP with terminal epistemic status (F or X). Rebuilt from Redis Streams XRANGE scan on Temporal workflow replay, satisfying NFR-007 (restart recovery without data loss). Used within the workflow to verify phase completion before proceeding.
- `run-lifecycle`: Run status state machine persisted to PostgreSQL via TypeORM. Drives status transitions (`pending` -> `ingesting` -> `analyzing` -> `synthesizing` -> `completed` | `cancelled` | `failed`) and exposes queryable state for the NestJS backend API.

### Modified Capabilities

- `redis-infrastructure` (slice 1): Adds orchestrator consumer group on agent streams -- `XREADGROUP` with group `orchestrator` for phase-gating. No structural changes to stream format.

## Impact

- **New module**: `services/agent-service/src/workflows/` and `services/agent-service/src/activities/` (Python)
- **Dependencies**: `temporalio` Python SDK, `asyncio`, existing `swarm_reasoning` models from slice 1
- **Infrastructure**: Temporal server added to docker-compose; orchestrator runs as a Temporal worker within the Python agent-service container
- **All agent slices** will depend on the Temporal activity interface defined here
- **NestJS backend** starts workflows via `TemporalClientAdapter` and queries run status from PostgreSQL
- **References**: ADR-0016 (supersedes ADR-0009 and ADR-0010)
