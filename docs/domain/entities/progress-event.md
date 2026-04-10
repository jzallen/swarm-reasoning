# Entity: ProgressEvent

## Description

A user-friendly status message published by an agent to the progress stream during execution. Progress events are relayed to the frontend via SSE, allowing users to watch the agent pipeline work in real-time.

## Invariants

- **INV-1**: A progress event must identify the agent that produced it.
- **INV-2**: A progress event must have a non-empty message string.
- **INV-3**: A progress event must have a timestamp.
- **INV-4**: Progress events are append-only — they cannot be modified after publication.
- **INV-5**: Progress events are only published between an agent's START and STOP messages.

## Value Objects

| Name | Type | Constraints |
|------|------|-------------|
| `ProgressPhase` | Enum | `ingestion` · `fanout` · `synthesis` · `finalization` |
| `ProgressType` | Enum | `agent-started` · `agent-progress` · `agent-completed` · `verdict-ready` · `session-frozen` |

## Schema

```typescript
interface ProgressEvent {
  runId:     string;          // e.g. "claim-4821-run-003"
  agent:     string;          // e.g. "coverage-left"
  phase:     ProgressPhase;
  type:      ProgressType;
  message:   string;          // user-friendly text, e.g. "Searching left-leaning sources..."
  timestamp: string;          // ISO 8601 UTC
}
```

## Creation Rules

- **Created by**: Agent workers (during activity execution)
- **Published to**: Redis Stream at key `progress:{runId}`
- **Relayed by**: NestJS backend via `StreamProgressUseCase` → SSE endpoint
- **Final event**: Backend publishes a `verdict-ready` event with the verdict payload, then `session-frozen` to signal close

## Aggregate Boundary

- **Owned by**: Session (via runId)
- **Stored in**: Redis Stream at key `progress:{runId}` (ephemeral, cleaned up with session)
- **Consumed by**: NestJS backend (SSE relay), static HTML renderer (chat progress view)

## SSE Event Format

```
event: progress
data: {"agent":"coverage-left","phase":"fanout","type":"agent-progress","message":"Searching left-leaning sources...","timestamp":"2026-04-10T12:00:05Z"}

event: verdict
data: {"type":"verdict-ready","verdict":{...}}

event: close
data: {"type":"session-frozen"}
```
