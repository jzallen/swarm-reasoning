# Entity: Run

## Description

A single end-to-end execution of the agent pipeline within a session. A run coordinates 11 agents across three phases to produce a verdict. The run is implemented as a Temporal workflow.

## Invariants

- **INV-1**: A run belongs to exactly one session.
- **INV-2**: Run status must be one of: `pending`, `ingesting`, `analyzing`, `synthesizing`, `completed`, `cancelled`, `failed`.
- **INV-3**: A run can only transition forward through its status sequence (no backwards transitions).
- **INV-4**: A completed run must have exactly one verdict.
- **INV-5**: A run must not complete until all expected agents have emitted a terminal status (`F` or `X`).

## Value Objects

| Name | Type | Constraints |
|------|------|-------------|
| `RunId` | string | Format: `{claim_slug}-run-{seq}`, immutable after creation |
| `RunStatus` | Enum | `pending` · `ingesting` · `analyzing` · `synthesizing` · `completed` · `cancelled` · `failed` |
| `Phase` | Enum | `ingestion` · `fanout` · `synthesis` |

## State Transitions

```
                Phase 1           Phase 2            Phase 3           All agents
  ┌─────────┐  starts   ┌───────────┐  starts  ┌─────────────┐ starts ┌──────────────┐  done  ┌───────────┐
  │ pending │ ────────► │ ingesting │ ───────► │  analyzing  │ ─────► │ synthesizing │ ─────► │ completed │
  └─────────┘           └───────────┘          └─────────────┘        └──────────────┘        └───────────┘
       │                      │ │                     │                      │
       │                      │ │ score < 0.4         │                      │
       │                      │ ▼                     │                      │
       │                      │ ┌────────────┐        │                      │
       │                      │ │ cancelled  │        │                      │
       │                      │ └────────────┘        │                      │
       │                      │                       │                      │
       └──────────────────────┴───────────────────────┴──────────────────────┘
                                    any unrecoverable error
                                           │
                                     ┌──────────┐
                                     │  failed  │
                                     └──────────┘
```

## Creation Rules

- **Requires**: Session ID, claim text
- **Generates**: Run ID, Temporal workflow ID, initial status `pending`
- **Side effect**: Starts Temporal workflow via `TemporalClientAdapter`

## Aggregate Boundary

- **Root**: Run
- **Contains**: Agent execution records (which agents ran, their terminal statuses)
- **References** (by ID): Session, Verdict
- **Produces**: Observation streams in Redis (`reasoning:{runId}:{agent}`)

## Phase Execution

| Phase | Agents | Execution |
|-------|--------|-----------|
| 1 — Ingestion | ingestion-agent → claim-detector → entity-extractor | Sequential |
| 2 — Fan-out | claimreview-matcher, coverage-left/center/right, domain-evidence, source-validator | Parallel |
| 3 — Synthesis | blindspot-detector → synthesizer | Sequential |
