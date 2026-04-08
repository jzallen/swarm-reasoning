# Observation Schema Specification — swarm-reasoning

**Version:** 0.2.0
**Wire Format:** JSON over Redis Streams
**Supersedes:** hl7-segment-spec.md (v0.1.0, HL7v2 ORU^R01)

This document defines the observation schema used for inter-agent
communication. All agents must conform to this spec. The tool layer
enforces conformance at write time by validating against these rules.

---

## 1. Stream Message Structure

Every inter-agent data exchange is a sequence of stream messages published
to a Redis Stream. A complete agent reasoning session consists of:

```
START        — exactly one, opens the stream
OBS[1..N]    — one or more observations, in sequence order
STOP         — exactly one, closes the stream
```

All messages are JSON objects with a `type` discriminator field.

---

## 2. Stream Message Types

### 2.1 START Message

Published when an agent begins reasoning for a run. Opens the stream.

```json
{
  "type": "START",
  "runId": "claim-4821-run-003",
  "agent": "coverage-left",
  "phase": "fanout",
  "timestamp": "2026-04-06T12:00:01Z"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `type` | `"START"` | yes | Discriminator |
| `runId` | string | yes | Format: `{claim_slug}-run-{seq}` |
| `agent` | string | yes | Agent bundle name, e.g. `coverage-left` |
| `phase` | string | yes | `ingestion`, `fanout`, or `synthesis` |
| `timestamp` | string | yes | ISO 8601 UTC |

### 2.2 OBS Message (Observation)

Published for each finding, hypothesis, or measurement. Append-only —
once published, an observation is immutable.

```json
{
  "type": "OBS",
  "observation": {
    "runId": "claim-4821-run-003",
    "agent": "coverage-left",
    "seq": 4,
    "code": "COVERAGE_FRAMING",
    "value": "SUPPORTIVE^Supportive^FCK",
    "valueType": "CWE",
    "units": null,
    "referenceRange": null,
    "status": "P",
    "timestamp": "2026-04-06T12:00:03Z",
    "method": "analyze_coverage",
    "note": null
  }
}
```

See Section 3 for the full Observation schema.

### 2.3 STOP Message

Published when an agent completes reasoning for a run. Closes the stream.

```json
{
  "type": "STOP",
  "runId": "claim-4821-run-003",
  "agent": "coverage-left",
  "finalStatus": "F",
  "observationCount": 12,
  "timestamp": "2026-04-06T12:00:08Z"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `type` | `"STOP"` | yes | Discriminator |
| `runId` | string | yes | Must match the START message |
| `agent` | string | yes | Must match the START message |
| `finalStatus` | `"F"` or `"X"` | yes | Terminal status for this agent's contribution |
| `observationCount` | number | yes | Total OBS messages published in this stream |
| `timestamp` | string | yes | ISO 8601 UTC |

---

## 3. Observation Schema

```typescript
interface Observation {
  runId:          string;    // run identifier
  agent:          string;    // agent bundle name
  seq:            number;    // sequential integer, 1-based, assigned by tool layer
  code:           string;    // from obx-code-registry.json
  value:          string;    // typed value as string
  valueType:      'ST' | 'NM' | 'CWE' | 'TX';
  units:          string | null;
  referenceRange: string | null;
  status:         'P' | 'F' | 'C' | 'X';
  timestamp:      string;    // ISO 8601 UTC
  method:         string | null;
  note:           string | null;  // ≤ 512 chars, replaces NTE segment
}
```

### 3.1 Field Details

| Field | Description |
|---|---|
| `runId` | Identifies the fact-checking run. Format: `{claim_slug}-run-{seq}` |
| `agent` | Name of the agent that produced this observation. Must match the agent's registered name in `obx-code-registry.json`. |
| `seq` | Sequential integer starting at 1. Assigned by the tool layer, never reused within a stream. |
| `code` | Observation code from `obx-code-registry.json`. The tool layer rejects unknown codes. |
| `value` | The observation value, encoded as a string regardless of type. See Section 3.2. |
| `valueType` | Determines how `value` should be interpreted. See Section 3.2. |
| `units` | Unit of measurement for `NM` values, e.g. `"score"`, `"count"`. Null for non-numeric types. |
| `referenceRange` | Expected range for numeric values, e.g. `"0.0-1.0"`. Null when not applicable. |
| `status` | Epistemic state. See Section 4. |
| `timestamp` | When the observation was produced. ISO 8601 UTC. Set by tool layer. |
| `method` | Name of the MCP tool or function that produced this observation. Null if not tool-generated. |
| `note` | Optional free-text annotation. Replaces the HL7v2 NTE segment. Max 512 characters. |

### 3.2 Value Types

| Type | Used For | Value Format | Example |
|---|---|---|---|
| `ST` | Short strings ≤ 200 chars | Plain string | `"Reuters"` |
| `NM` | Numeric values | Decimal string | `"0.84"` |
| `TX` | Long text > 200 chars | Plain string | `"Full narrative summary..."` |
| `CWE` | Coded values with display text | `{code}^{display}^{system}` | `"TRUE^True^POLITIFACT"` |

### 3.3 Correction Pattern

When an agent corrects a prior observation, it publishes a new OBS message
with `C` status. The corrected observation carries the same `code`. The
original observation is not modified (append-only log, ADR-003).

```json
{"type": "OBS", "observation": {"seq": 7, "code": "CONFIDENCE_SCORE", "value": "0.84", "status": "F", "..."}}
...
{"type": "OBS", "observation": {"seq": 23, "code": "CONFIDENCE_SCORE", "value": "0.61", "status": "C", "..."}}
```

Observation seq 23 supersedes seq 7. The synthesizer resolves by selecting
the most recent `F` or `C` entry for each code.

---

## 4. Epistemic Status Semantics

| Value | Label | Meaning | Synthesizer Behavior |
|---|---|---|---|
| `P` | Preliminary | Hypothesis or initial finding, not yet corroborated | Informational only, not used in final verdict |
| `F` | Final | Agent considers this finding settled | Authoritative input to synthesis |
| `C` | Corrected | Supersedes an earlier observation of the same code | Authoritative input, replaces prior `F` |
| `X` | Cancelled | Claim not check-worthy or finding retracted | Excluded from synthesis, retained for audit |

An agent may publish `P` observations freely during reasoning and must
publish at least one `F` or `X` observation for each of its registered
codes before the orchestrator considers it complete (see ADR-005, ADR-010).

---

## 5. Observation Identifier

The `code` field references the canonical code from `obx-code-registry.json`.
The coding system identifier `FCK` is retained in the registry metadata
but is not embedded in observation values.

Example — a confidence score observation:
```json
{
  "code": "CONFIDENCE_SCORE",
  "value": "0.84",
  "valueType": "NM",
  "units": "score",
  "referenceRange": "0.0-1.0",
  "status": "F"
}
```

---

## 6. Redis Stream Key Design

```
reasoning:{runId}:{agent}     — per-agent observation stream
```

Each agent publishes to its own stream key. The orchestrator subscribes
to all agent streams for a given run using `XREADGROUP`.

Stream entry IDs are auto-generated by Redis (`*`), providing
monotonically increasing timestamps that serve as the global ordering
for log resolution.

---

## 7. Delivery Acknowledgment

Redis Streams consumer groups provide delivery acknowledgment. The
orchestrator uses `XACK` to confirm processing of each message.
Unacknowledged messages can be reclaimed via `XPENDING` and `XCLAIM`.

This replaces the HL7v2 ACK/NACK mechanism (MSA segment). The semantics
map as follows:

| HL7v2 ACK (former) | Redis Streams (current) |
|---|---|
| `AA` (Application Accept) | `XACK` — message processed |
| `AE` (Application Error) | No ACK — message remains pending, reclaimable |
| `AR` (Application Reject) | Dead-letter handling (application-level) |

---

## 8. Observation Code Ownership

Each observation code in `obx-code-registry.json` has an `owner_agent`
field. The tool layer enforces ownership at write time: only the
designated owner agent may publish observations with that code.

Codes owned by multiple agents (e.g. `COVERAGE_ARTICLE_COUNT` owned by
`coverage-left|coverage-center|coverage-right`) use pipe-delimited
owner lists. The tool layer checks that the publishing agent appears
in the owner list.

---

## 9. Verdict Mapping to PolitiFact Scale

The synthesizer publishes a `VERDICT` observation of type `CWE`. The
coded value maps to PolitiFact's six-tier scale:

| Value (CWE format) | PolitiFact Equivalent | Confidence Range |
|---|---|---|
| `TRUE^True^POLITIFACT` | True | 0.85 - 1.00 |
| `MOSTLY_TRUE^Mostly True^POLITIFACT` | Mostly True | 0.70 - 0.84 |
| `HALF_TRUE^Half True^POLITIFACT` | Half True | 0.45 - 0.69 |
| `MOSTLY_FALSE^Mostly False^POLITIFACT` | Mostly False | 0.25 - 0.44 |
| `FALSE^False^POLITIFACT` | False | 0.10 - 0.24 |
| `PANTS_FIRE^Pants on Fire^POLITIFACT` | Pants on Fire | 0.00 - 0.09 |
| `UNVERIFIABLE^Unverifiable^FCK` | No PolitiFact equivalent | N/A |

The `CONFIDENCE_SCORE` observation (`NM` type, 0.0-1.0) drives the
verdict mapping. The synthesizer publishes both observations together
with `F` status. `UNVERIFIABLE` is used when insufficient evidence
exists for a confidence score.

---

## 10. Stream Conventions

- Stream keys follow the pattern: `reasoning:{runId}:{agent}`
- Entry IDs: auto-generated by Redis (`*` on `XADD`)
- Character encoding: UTF-8
- Timestamps: ISO 8601 UTC (e.g. `2026-04-06T12:00:03Z`)
- Null fields: included in JSON as `null`, not omitted
- Maximum observation value size: 1 MB (Redis default max entry size)
