---
status: accepted
date: 2026-04-08
deciders: []
---

# ADR-0004: Tool-Based Observation Construction

## Context and Problem Statement

Agents must produce valid observation entries as part of their output. Two approaches exist: the LLM generates raw observation JSON directly, or the LLM calls structured tools that produce valid entries internally.

LLM generation of structured formats is a known failure mode. Even with JSON, deeply nested schemas with specific field conventions and coded values are error-prone. A single malformed observation can corrupt downstream processing.

Tool-based construction moves structural responsibility to deterministic code. The LLM decides *what* to assert; the tool decides *how* to serialize it. Structural errors become impossible. Semantic errors (wrong interpretation) remain, but they are recoverable and auditable.

## Decision Drivers

- LLM generation of structured formats is error-prone, especially for deeply nested schemas
- A single malformed observation can corrupt downstream processing
- Structural correctness must be guaranteed
- Observation codes must be validated against the registry at write time

## Considered Options

1. **LLM-generated observation strings** — The LLM generates raw observation JSON directly. Structurally fragile; a single malformed entry can corrupt downstream processing.
2. **Tool-based construction** — The LLM calls structured tools that produce valid observation entries internally. Structural correctness is guaranteed by the tool layer.

## Decision Outcome

Chosen option: "Tool-based construction", because it moves structural responsibility to deterministic code. The LLM's role is limited to deciding which tools to call and with what values — which is exactly what LLMs are reliable at. The tool surface is small and stable:

```typescript
startStream(runId, agent, phase)
publishObservation({ code, value, valueType, units, range, status })
stopStream(runId, agent, finalStatus)
```

Structural correctness is guaranteed by the tool layer.

### Consequences

- Good, because structural errors in observations become impossible
- Good, because observation code validation against the registry happens at write time
- Good, because the tool layer enforces observation code ownership — only the agent registered as the owner of a given code can write it
- Bad, because every new observation code must be registered in `obx-code-registry.json` before agents can use it — the tool rejects unknown codes
