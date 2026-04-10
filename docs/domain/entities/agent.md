# Entity: Agent

## Description

A specialized software component that performs one step of the fact-checking pipeline. Each agent is a LangChain-powered reasoning process running as a Temporal worker. Agents communicate exclusively through observations published to Redis Streams — they do not communicate directly with each other.

## Invariants

- **INV-1**: An agent can only publish observations with codes it owns (per the observation code registry).
- **INV-2**: An agent reasoning session must begin with exactly one START message and end with exactly one STOP message.
- **INV-3**: Between START and STOP, an agent must publish one or more observations.
- **INV-4**: The STOP message must carry a terminal epistemic status: `F` (final) or `X` (cancelled).
- **INV-5**: An agent must not publish observations outside a START/STOP session boundary.
- **INV-6**: Each agent type has exactly one Temporal worker.
- **INV-7**: Agents are stateless — all state is in Redis Streams.

## Value Objects

| Name | Type | Constraints |
|------|------|-------------|
| `AgentName` | string | One of the 11 registered agent names |
| `AgentPhase` | Enum | `ingestion` (Phase 1) · `fanout` (Phase 2) · `synthesis` (Phase 3) |

## Agent Registry

| Name | Phase | Role | External Dependencies |
|------|-------|------|----------------------|
| `ingestion-agent` | 1 | Claim intake, entity extraction, check-worthiness gate | None |
| `claim-detector` | 1 | Check-worthiness scoring, claim normalization | None |
| `entity-extractor` | 1 | Named entity recognition | None |
| `claimreview-matcher` | 2 | Existing fact-check lookup | Google Fact Check Tools API |
| `coverage-left` | 2 | Left-leaning source analysis | NewsAPI |
| `coverage-center` | 2 | Centrist source analysis | NewsAPI |
| `coverage-right` | 2 | Right-leaning source analysis | NewsAPI |
| `domain-evidence` | 2 | Domain-specific primary sources | CDC, SEC, WHO, PubMed, etc. |
| `source-validator` | 2 | URL extraction, validation, convergence | HTTP HEAD requests |
| `blindspot-detector` | 3 | Coverage gap identification | None (reads other agents' streams) |
| `synthesizer` | 3 | Observation resolution, verdict emission | None (reads all streams) |

## Session Protocol

```
Agent Worker receives Temporal activity
  │
  ├─► Publish START message to reasoning:{runId}:{agent}
  │     └─ {type: "START", runId, agent, phase, timestamp}
  │
  ├─► LangChain agent reasons using tools
  │     ├─ Tool calls publish OBS messages
  │     │     └─ {type: "OBS", observation: {...}}
  │     └─ Agent publishes progress events to progress:{runId}
  │
  └─► Publish STOP message
        └─ {type: "STOP", runId, agent, finalStatus: "F"|"X", observationCount}
```

## Aggregate Boundary

- **Not an aggregate root** — agents are dispatched by the orchestrator Temporal workflow
- **Owns**: Its observation codes (per registry)
- **Writes to**: `reasoning:{runId}:{agent}` (observations), `progress:{runId}` (progress events)
- **Reads from**: Other agents' streams (blindspot-detector, source-validator — via orchestrator-provided data)
