---
status: accepted
date: 2026-04-08
deciders: []
---

# ADR-0011: JSON Observation Schema

## Context and Problem Statement

ADR-001 chose HL7v2 pipe-delimited messaging as the inter-agent wire format. The rationale centered on three properties: line-level validity for streaming, native epistemic status (OBX.11 result status), and zero-serialization alignment with YottaDB storage.

Re-evaluation revealed that these properties are not unique to HL7v2:

1. **Epistemic status** — The P/F/C/X model is a four-value enum. A `status` field in a JSON object carries identical semantics.
2. **Streaming** — Redis Streams delivers discrete messages. Each message is independently valid regardless of format. The streaming argument applies to the transport layer, not the encoding.
3. **YottaDB alignment** — With YottaDB superseded (ADR-0012), the zero-serialization-gap argument is circular and no longer applies.
4. **Edge serialization** — HL7v2 required a dedicated serialization adapter (ADR-0006) to produce JSON for external consumers. A native JSON format eliminates this translation layer entirely.

The HL7v2 encoding added domain-specific complexity (escape sequences, positional field semantics, MLLP framing) without functional benefit over a well-typed JSON schema. The cross-domain insight — that healthcare protocols solved epistemic state tracking, append-only audit, and provenance decades ago — informed the design of the replacement schema. The insight is preserved; the encoding is not.

## Decision Drivers

- HL7v2 properties (epistemic status, streaming, provenance) are achievable with typed JSON
- YottaDB alignment argument is circular once YottaDB is superseded
- HL7v2 encoding adds domain-specific complexity without functional benefit
- Edge serialization adapter (ADR-0006) exists only because internal format differs from external format
- Cross-domain insight from healthcare protocols should be preserved in the schema design

## Considered Options

1. **Retain HL7v2 pipe-delimited format** — Keep the existing wire format. Preserves native OBX.11 semantics but retains unnecessary complexity and requires edge serialization.
2. **Typed JSON observation schema** — Encode observations as typed JSON objects with explicit status fields. Preserves epistemic state model while eliminating HL7v2 complexity and the edge serialization layer.

## Decision Outcome

Chosen option: "Typed JSON observation schema", because the epistemic status model, append-only semantics, and observation structure are preserved while eliminating HL7v2 encoding complexity and the edge serialization layer.

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

- Good, because the edge-serializer agent is eliminated — the consumer API reads JSON observations directly from Redis Streams
- Good, because no escape sequence handling is needed — JSON string escaping is handled by standard libraries
- Good, because the cross-domain insight from healthcare protocols is preserved in the schema design (P/F/C/X status model)
- Neutral, because the `obx-code-registry.json` file is unchanged — the `FCK` coding system identifier is retained in the registry but is not encoded into observation values (unlike the HL7v2 `{code}^^FCK` pattern)
- Neutral, because CWE-typed values use a structured format: `{code}^{display}^{system}` stored as a string, consistent with the registry; implementations may alternatively parse this into a structured object
- Neutral, because verdict mapping to PolitiFact scale is unchanged (see observation schema spec, Section 9)

## More Information

Supersedes [ADR-0001](0001-hl7v2-wire-format.md) and [ADR-0006](0006-edge-serialization-mirth.md).
