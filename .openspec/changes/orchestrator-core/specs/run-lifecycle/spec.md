# Capability: run-lifecycle

## Purpose

Manage run status as a state machine persisted to PostgreSQL via TypeORM. Drive status transitions from `pending` through to `completed`, `cancelled`, or `failed`. Expose queryable state for the NestJS backend API without requiring the Temporal workflow to be running. Status updates are performed by Temporal activities called from within the `ClaimVerificationWorkflow`.

## Behaviour

### Status values

| Status | Meaning |
|--------|---------|
| `pending` | Run created; workflow not yet started or Phase 1 not yet begun |
| `ingesting` | Phase 1 (sequential ingestion) in progress: ingestion-agent, claim-detector, entity-extractor |
| `analyzing` | Phase 2 (parallel fan-out) in progress: 6 agents running concurrently |
| `synthesizing` | Phase 3 (sequential synthesis) in progress: blindspot-detector, synthesizer |
| `completed` | Synthesizer has emitted STOP with status F; verdict extracted and stored |
| `cancelled` | Run terminated by check-worthiness gate (claim-detector score < 0.4) |
| `failed` | Run terminated by unrecoverable error (agent failure after retries, infrastructure error) |

### State machine transitions

```
pending -> ingesting        (workflow starts Phase 1)
ingesting -> analyzing      (Phase 1 complete; all 3 sequential agents done)
analyzing -> synthesizing   (Phase 2 complete; all 6 parallel agents done)
synthesizing -> completed   (Phase 3 complete; verdict extracted)
{pending, ingesting} -> cancelled   (check-worthiness gate rejects claim)
{pending, ingesting, analyzing, synthesizing} -> failed   (unrecoverable error)
```

Invalid transitions raise `InvalidRunTransition`. No other transitions are permitted. Terminal states (`completed`, `cancelled`, `failed`) cannot transition further.

### PostgreSQL persistence

Run status is stored in the `runs` PostgreSQL table managed by TypeORM in the NestJS backend:

```sql
-- Columns relevant to run lifecycle (subset of full Run entity)
id              UUID PRIMARY KEY
session_id      UUID REFERENCES sessions(id)
status          VARCHAR(20) NOT NULL DEFAULT 'pending'
claim_text      TEXT NOT NULL
started_at      TIMESTAMPTZ
updated_at      TIMESTAMPTZ
completed_at    TIMESTAMPTZ
cancelled_at    TIMESTAMPTZ
failed_at       TIMESTAMPTZ
cancel_reason   TEXT
error_message   TEXT
workflow_id     VARCHAR(255)  -- Temporal workflow ID
```

All writes from the Temporal workflow are performed via activities (non-deterministic I/O is not allowed in Temporal workflows). The `update_run_status` activity connects to PostgreSQL and updates the relevant columns.

### Temporal activities for lifecycle management

#### `update_run_status` activity

```python
@activity.defn
async def update_run_status(run_id: str, to_status: str) -> dict:
    """
    Validate transition, update PostgreSQL row, return updated status dict.
    Raises InvalidRunTransition if the current status does not permit the requested transition.
    """
```

#### `cancel_run` activity

```python
@activity.defn
async def cancel_run(run_id: str, reason: str = "") -> dict:
    """
    Transition to cancelled with reason. No-op if already cancelled or completed.
    """
```

#### `fail_run` activity

```python
@activity.defn
async def fail_run(run_id: str, error_message: str = "") -> dict:
    """
    Transition to failed with error message. No-op if already in terminal state.
    """
```

#### `get_run_status` activity

```python
@activity.defn
async def get_run_status(run_id: str) -> dict | None:
    """
    Read current run status from PostgreSQL. Returns None if not found.
    """
```

### Run creation

Run creation happens in the NestJS backend (not in the Temporal workflow). The backend creates the PostgreSQL row with `status = pending` and starts the Temporal workflow via `TemporalClientAdapter`. The workflow receives the `run_id` as input.

### Cancellation

The `cancel_run` activity transitions status to `cancelled` and sets `cancel_reason` and `cancelled_at`. Valid from `pending` or `ingesting` (check-worthiness gate). Calling cancel on an already-terminal run is a no-op (idempotent).

### Failure

The `fail_run` activity transitions status to `failed` and sets `error_message` and `failed_at`. Valid from any non-terminal status. Calling fail on an already-terminal run is a no-op.

### Query path

The NestJS backend queries PostgreSQL directly for run status via TypeORM repositories. No Temporal workflow needs to be running for a status query. The Temporal workflow ID is stored in the `workflow_id` column so the backend can query Temporal for workflow state if needed.

## Acceptance criteria

- `update_run_status` with transition `pending -> ingesting` succeeds.
- `update_run_status` with transition `ingesting -> analyzing` succeeds only when current status is `ingesting`.
- `update_run_status` with transition `analyzing -> synthesizing` succeeds only when current status is `analyzing`.
- `update_run_status` with transition `synthesizing -> completed` succeeds only when current status is `synthesizing`.
- `update_run_status` with an invalid transition raises `InvalidRunTransition`.
- `cancel_run` from `cancelled` or `completed` is a no-op (returns current status without error).
- `fail_run` from any terminal state is a no-op.
- `get_run_status` returns `None` for an unknown run ID.
- All timestamp fields (`started_at`, `updated_at`, etc.) use ISO-8601 UTC format.
- Run lifecycle transitions are consistent with the state diagram in `docs/domain/entities/run.md`.
- The NestJS backend can query run status from PostgreSQL without the Temporal workflow running.
- Temporal workflow ID is recorded in the run row for operational correlation.
