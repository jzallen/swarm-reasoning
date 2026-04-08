# Observation Stream Lifecycle — swarm-reasoning

**Version:** 0.2.0
**Supersedes:** hl7-message-lifecycle.md (v0.1.0)

This document explains how observation streams are opened, grown, consumed,
and finalized across a full fact-checking run. It is the narrative companion
to `c4-containers.mermaid` and `agent-topology.mermaid`.

---

## 1. Core Principle: Redis is the Data Plane, MCP is the Control Plane

The most important architectural distinction in this system is the
separation of **control** and **data** flows.

**MCP (control plane) handles:**
- Orchestrator → Agent: task assignment, configuration, queries
- Synchronous request/response
- Hub-and-spoke topology (orchestrator is sole MCP client)

**Redis Streams (data plane) handles:**
- Agent → Stream: observation publication (START, OBS, STOP)
- Orchestrator ← Stream: observation consumption via consumer groups
- Asynchronous append/subscribe
- Append-only audit log

**MCP does not handle:** streaming reasoning data, large observation payloads,
or completion detection (that comes from STOP messages on the data plane).

**Redis Streams does not handle:** task assignment, agent configuration,
or tool invocation (that stays on the control plane).

The two planes fail independently. If MCP is down, agents cannot receive
new tasks but can continue publishing observations. If Redis is down,
agents cannot publish but MCP commands still function.

---

## 2. Stream Lifecycle Phases

### Phase 0 — Stream Initialization

Triggered when the orchestrator dispatches the ingestion agent via MCP.
The ingestion agent's tool layer opens a new stream:

```
XADD reasoning:claim-4821-run-003:ingestion-agent *
  type START
  runId claim-4821-run-003
  agent ingestion-agent
  phase ingestion
  timestamp 2026-04-06T12:00:00Z
```

The first observations are written at `P` status:

```
XADD reasoning:claim-4821-run-003:ingestion-agent *
  type OBS
  payload '{"seq":1,"code":"CLAIM_TEXT","value":"Biden issued a federal vaccine mandate...","status":"P",...}'
```

The agent promotes to `F` once the claim is validated:

```
XADD reasoning:claim-4821-run-003:ingestion-agent *
  type OBS
  payload '{"seq":2,"code":"CLAIM_TEXT","value":"Biden issued a federal vaccine mandate...","status":"F",...}'
```

The agent closes its stream:

```
XADD reasoning:claim-4821-run-003:ingestion-agent *
  type STOP
  runId claim-4821-run-003
  agent ingestion-agent
  finalStatus F
  observationCount 5
  timestamp 2026-04-06T12:00:05Z
```

The orchestrator, subscribed via `XREADGROUP`, receives these entries
in real time.

---

### Phase 1 — Sequential Processing

The orchestrator dispatches claim-detector and entity-extractor in
sequence via MCP. Each agent:

1. Receives its task via MCP tool call
2. Opens its own stream with a START message
3. Reads upstream observations via the `ReasoningStream.getObservations()`
   interface (which issues `XRANGE` on upstream agent streams)
4. Reasons and publishes OBS messages to its own stream
5. Emits `F` status observations when complete
6. Closes its stream with a STOP message

Each agent writes to its own stream key
(`reasoning:{runId}:{agent}`), so there are no write conflicts.
Sequence numbers are scoped per-agent stream — global ordering is
determined by Redis entry IDs.

By the end of Phase 1, the system contains streams from ingestion-agent,
claim-detector, and entity-extractor, covering `CLAIM_TEXT`,
`CLAIM_SOURCE_*`, `CHECK_WORTHY_SCORE`, `CLAIM_NORMALIZED`, and all
`ENTITY_*` codes.

---

### Phase 2 — Parallel Fan-Out

The orchestrator detects entity extraction is complete (STOP message
received with `finalStatus: "F"`). It simultaneously dispatches five
agents via MCP:

- ClaimReview Matcher
- Coverage Agent Left
- Coverage Agent Center
- Coverage Agent Right
- Domain Evidence Agent

Each parallel agent:
1. Opens its own stream with START (phase: `fanout`)
2. Reads entity observations from upstream streams via `getObservations()`
3. Calls external APIs (NewsAPI, Google Fact Check Tools, primary sources)
4. Publishes observations to its own stream
5. Emits `F` or `X` terminal status
6. Closes its stream with STOP

Because each agent publishes to its own stream, there are no write
conflicts between parallel agents. The orchestrator monitors all five
streams via `XREADGROUP` and tracks which agents have sent STOP in its
completion register.

---

### Phase 3 — Blindspot Detection

The orchestrator detects that the three coverage agents are all complete
(all three STOP messages received). It dispatches the blindspot detector:

1. Opens stream with START
2. Uses pull pattern: reads `COVERAGE_ARTICLE_COUNT` and
   `COVERAGE_FRAMING` observations from coverage agent streams via
   `getObservations(runId, { code: "COVERAGE_FRAMING" })`
3. Computes coverage asymmetry
4. Publishes `BLINDSPOT_SCORE`, `BLINDSPOT_DIRECTION`, and
   `CROSS_SPECTRUM_CORROBORATION` observations
5. Closes stream with STOP

---

### Phase 4 — Synthesis

The orchestrator detects all nine preceding agents have closed their
streams. It dispatches the synthesizer:

1. Opens stream with START (phase: `synthesis`)
2. Reads all observations across all agent streams via
   `getObservations(runId)` — this issues `XRANGE` on all 9 streams
3. Applies observation resolution logic (DMN DetermineOBXResolution —
   latest `C` wins, then latest `F`, `X` excluded)
4. Computes `CONFIDENCE_SCORE` from weighted upstream signals
5. Maps confidence score to `VERDICT` coded value
6. Publishes `VERDICT_NARRATIVE` as `TX` type observation
7. Publishes all synthesis observations at `F` status
8. Closes stream with STOP

The run transitions to `SYNTHESIZED`.

---

### Phase 5 — Publication

The consumer API reads the synthesized observations directly from Redis
Streams. No edge serialization adapter is needed — the observation format
is already JSON.

The consumer API:
1. Reads all `F` and `C` status observations for the run
2. Applies observation resolution (same logic as synthesizer)
3. Constructs the consumer-facing verdict response
4. Serves via REST API

The run transitions to `PUBLISHED`. The Redis Streams are retained as
the audit record. The API response is a projection of that record.

---

## 3. Observation Growth Over a Full Run

A typical run produces approximately 60–80 observations across all agents.

| Agent | Expected Observations | Codes |
|---|---|---|
| Ingestion | 3–5 | CLAIM_TEXT, CLAIM_SOURCE_URL, CLAIM_SOURCE_DATE, CLAIM_DOMAIN |
| Claim Detector | 2–3 | CHECK_WORTHY_SCORE, CLAIM_NORMALIZED |
| Entity Extractor | 4–12 | ENTITY_PERSON (xN), ENTITY_ORG (xN), ENTITY_DATE, ENTITY_LOCATION, ENTITY_STATISTIC |
| ClaimReview Matcher | 3–5 | CLAIMREVIEW_MATCH, CLAIMREVIEW_VERDICT, CLAIMREVIEW_SOURCE, CLAIMREVIEW_URL, CLAIMREVIEW_MATCH_SCORE |
| Coverage Left | 4 | COVERAGE_ARTICLE_COUNT, COVERAGE_FRAMING, COVERAGE_TOP_SOURCE, COVERAGE_TOP_SOURCE_URL |
| Coverage Center | 4 | Same codes, agent = coverage-center |
| Coverage Right | 4 | Same codes, agent = coverage-right |
| Blindspot Detector | 3 | BLINDSPOT_SCORE, BLINDSPOT_DIRECTION, CROSS_SPECTRUM_CORROBORATION |
| Domain Evidence | 4 | DOMAIN_SOURCE_NAME, DOMAIN_SOURCE_URL, DOMAIN_EVIDENCE_ALIGNMENT, DOMAIN_CONFIDENCE |
| Synthesizer | 4–6 | CONFIDENCE_SCORE, VERDICT, VERDICT_NARRATIVE, SYNTHESIS_SIGNAL_COUNT, SYNTHESIS_OVERRIDE_REASON |

`P` status observations are additional — agents may publish several
before promoting to `F`. The append-only log retains all of them.

---

## 4. Stream Identity and Correlation

The run ID (e.g. `claim-4821-run-003`) is the correlation key for the
entire lifecycle. It appears in:

- Redis Stream key prefix: `reasoning:{runId}:*`
- Every observation's `runId` field
- Every START/STOP message's `runId` field
- Consumer API response as `runId` field

Any agent, at any point, can read the full observation state for a run
by querying `getObservations(runId)`. The `ReasoningStream` interface
handles fan-out across all agent streams for that run. No agent needs
to know which other agents exist — it reads observations by code, not
by agent.

---

## 5. Failure and Recovery

**Agent failure mid-run:**
The orchestrator detects a missing STOP message after a configurable
timeout. It retries the MCP dispatch up to 3 times. If the agent remains
unreachable, the run is marked `ERROR`. Observations already published
by other agents are preserved in Redis Streams. The run can be resumed
once the failed agent is restored — the orchestrator checks
`isComplete(runId, expectedAgents)` and re-dispatches only incomplete
agents.

**Orchestrator restart:**
The orchestrator is stateless (ADR-010). On restart, it scans Redis
Streams for in-progress runs (streams with START but no STOP), calls
`isComplete()` to reconstruct the completion register, and resumes
from the correct phase.

**Redis data loss:**
The observation log is the ground truth. Redis persistence must be
configured appropriately:
- **Development:** RDB snapshots at default intervals (acceptable loss)
- **Production:** AOF with `appendfsync everysec` or Kafka graduation
  (ADR-012) for durability guarantees

Backup strategy for Redis data is out of scope for the prototype but
must be addressed before any production deployment.
