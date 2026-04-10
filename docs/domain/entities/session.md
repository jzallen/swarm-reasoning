# Entity: Session

## Description

A bounded processing context that owns exactly one claim and all artifacts produced while checking it. Sessions are ephemeral — they exist for 3 days after the verdict is finalized, then are deleted with all associated data.

## Invariants

- **INV-1**: A session must have exactly one claim.
- **INV-2**: Session status must be one of: `active`, `frozen`, `expired`.
- **INV-3**: A frozen session cannot accept new claims.
- **INV-4**: A session can only transition forward: `active → frozen → expired`.
- **INV-5**: A session must have a non-empty session ID (UUID v4), immutable after creation.

## Value Objects

| Name | Type | Constraints |
|------|------|-------------|
| `SessionId` | UUID v4 | Immutable after creation. Used in URL path: `/{sessionId}` |
| `SessionStatus` | Enum | `active` · `frozen` · `expired` |

## State Transitions

```
                  verdict finalized         3-day TTL elapsed
    ┌────────┐ ──────────────────► ┌────────┐ ──────────────► ┌─────────┐
    │ active │                     │ frozen │                  │ expired │
    └────────┘                     └────────┘                  └─────────┘
         │                              │                           │
     SSE open                    Serve static HTML            Cleanup job
     Chat active                 SSE closed                   deletes all
     Claim mutable               No interaction               associated data
```

## Creation Rules

- **Requires**: claim text (non-empty string, max 2000 characters)
- **Generates**: session ID (UUID v4), created timestamp (UTC), initial status `active`
- **Side effects**: Updates `window.location` with session ID on frontend

## Aggregate Boundary

- **Root**: Session
- **Contains**: Claim (1:1), ProgressEvents (1:N)
- **References** (by ID): Run, Verdict

## Lifecycle

1. User submits claim → Session created with status `active`
2. Orchestrator workflow runs → ProgressEvents stream to frontend via SSE
3. Synthesizer emits verdict → `FinalizeSessionUseCase` freezes session, renders static HTML
4. 3 days elapse → `CleanupExpiredSessionsUseCase` deletes session, snapshot, and database rows
