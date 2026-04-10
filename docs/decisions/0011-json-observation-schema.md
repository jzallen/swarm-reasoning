---
status: accepted
date: 2026-04-08
deciders: []
---

# ADR-0011: JSON Observation Schema

## Context and Problem Statement

Agents in the swarm-reasoning system need a shared wire format for typed observations published to Redis Streams. The format must carry epistemic state (P/F/C/X status), support append-only log semantics, and be directly consumable by the consumer API without a translation layer.

The observation schema must encode agent identity, observation codes from the registry, typed values, and lifecycle events (START, OBS, STOP). It must be validated at the tool layer (ADR-0004) and readable by the synthesizer for log resolution.

## Decision Drivers

- Observations must carry epistemic state, provenance, and typed values in a single schema
- The consumer API must read observations directly without a translation layer
- Standard JSON tooling (validators, serializers, TypeScript interfaces) must work out of the box
- The schema must be streamable as discrete Redis Stream messages
- Type safety must be enforceable at the tool layer via registry validation

## Considered Options

1. **Typed JSON observation schema** — Encode observations as typed JSON objects with explicit status, code, and value fields. Directly consumable by the API and streamable via Redis Streams.
2. **Protocol Buffers** — Binary encoding with schema evolution support. Efficient on the wire but requires compilation step and is not human-readable in Redis Stream inspection.
3. **Avro with Schema Registry** — Schema-evolved binary format. Adds operational complexity (schema registry service) disproportionate to the prototype's needs.

## Decision Outcome

Chosen option: "Typed JSON observation schema", because it carries epistemic state, provenance, and typed values in a human-readable format that is directly consumable by the consumer API, streamable via Redis Streams, and enforceable at the tool layer.

Observations are encoded as typed JSON objects conforming to the following schema:

```typescript
interface Observation {
  runId:          string;       // e.g. "claim-4821-run-003"
  agent:          string;       // e.g. "coverage-left"
  seq:            number;       // sequential, assigned by tool layer
  code:           string;       // from obx-code-registry.json
  value:          string;       // typed value as string
  valueType:      'ST' | 'NM' | 'CWE' | 'TX';
  units?:         string;       // e.g. "score", "count"
  referenceRange?: string;      // e.g. "0.0-1.0"
  status:         'P' | 'F' | 'C' | 'X';  // epistemic state
  timestamp:      string;       // ISO 8601 UTC
  method?:        string;       // which tool produced this
}
```

Stream messages are framed with explicit lifecycle events:

```typescript
type StreamMessage =
  | { type: 'START'; runId: string; agent: string; phase: string }
  | { type: 'OBS';   observation: Observation }
  | { type: 'STOP';  runId: string; agent: string;
      finalStatus: 'F' | 'X'; observationCount: number };
```

The observation code registry (`obx-code-registry.json`) remains the governing contract for valid codes, value types, ownership, and reference ranges. The tool layer validates against it at write time.

### Consequences

- Good, because the consumer API reads JSON observations directly from Redis Streams without a translation layer
- Good, because JSON string escaping is handled by standard libraries — no custom encoding logic
- Good, because the P/F/C/X epistemic status model is a first-class typed field in the schema
- Neutral, because the `obx-code-registry.json` file governs valid codes, value types, ownership, and reference ranges — the `FCK` coding system identifier is retained in the registry
- Neutral, because CWE-typed values use a structured format: `{code}^{display}^{system}` stored as a string, consistent with the registry; implementations may alternatively parse this into a structured object
- Neutral, because verdict mapping to PolitiFact scale is unchanged (see observation schema spec, Section 9)

