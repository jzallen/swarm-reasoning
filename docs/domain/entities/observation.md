# Entity: Observation

## Description

A typed, immutable JSON record published by an agent to the observation log. Observations are the fundamental unit of inter-agent communication — agents reason by reading observations from other agents and publishing their own findings.

## Invariants

- **INV-1**: An observation is immutable once published. It cannot be modified or deleted.
- **INV-2**: An observation must have an observation code from the observation code registry.
- **INV-3**: An observation can only be published by the agent that owns its observation code.
- **INV-4**: An observation must have an epistemic status.
- **INV-5**: An observation must belong to a run (via `runId`).
- **INV-6**: An observation must have a sequential `seq` number, assigned by the tool layer, unique within the agent's stream for that run.
- **INV-7**: A corrected observation (status `C`) must use the same observation code as the observation it corrects.

## Value Objects

| Name | Type | Constraints |
|------|------|-------------|
| `ObservationCode` | string | Must exist in `obx-code-registry.json`. Validated at write time by tool layer. |
| `EpistemicStatus` | Enum | `P` (preliminary) · `F` (final) · `C` (corrected) · `X` (cancelled) |
| `ValueType` | Enum | `ST` (string) · `NM` (numeric) · `CWE` (coded with extensions) · `TX` (text) |

## Schema

```typescript
interface Observation {
  runId:           string;       // e.g. "claim-4821-run-003"
  agent:           string;       // e.g. "coverage-left"
  seq:             number;       // sequential, assigned by tool layer
  code:            string;       // from obx-code-registry.json
  value:           string;       // typed value as string
  valueType:       'ST' | 'NM' | 'CWE' | 'TX';
  units?:          string;       // e.g. "score", "count"
  referenceRange?: string;       // e.g. "0.0-1.0"
  status:          'P' | 'F' | 'C' | 'X';
  timestamp:       string;       // ISO 8601 UTC
  method?:         string;       // which tool produced this
  note?:           string;       // optional free-text annotation, max 512 chars
}
```

## Creation Rules

- **Created by**: Tool layer (LLMs never construct observations directly — ADR-004)
- **Requires**: runId, agent, code, value, valueType, status
- **Generates**: seq number (auto-incremented within agent stream), timestamp
- **Validation**: Code checked against registry, agent ownership verified, value type validated

## Aggregate Boundary

- **Owned by**: Run (via runId) and Agent (via agent field)
- **Stored in**: Redis Stream at key `reasoning:{runId}:{agent}`
- **Read by**: Synthesizer (all observations), blindspot-detector (cross-agent), source-validator (URLs)

## Resolution Rules

When multiple observations exist for the same code within a run:
1. Only `F` (final) and `C` (corrected) status observations are authoritative
2. The most recent `F` or `C` entry is the current value
3. `P` (preliminary) observations are informational only
4. `X` (cancelled) observations are excluded from synthesis but retained for audit
