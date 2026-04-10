# Observation Stream Lifecycle — swarm-reasoning

**Version:** 0.3.0

This document explains how observation streams are opened, grown, consumed,
and finalized across a full fact-checking run. It is the narrative companion
to `c4-containers.mermaid` and `agent-topology.mermaid`.

---

## 1. Core Principle: Redis is the Data Plane, Temporal is the Control Plane

The most important architectural distinction in this system is the
separation of **control** and **data** flows.

**Temporal (control plane) handles:**
- Backend → Temporal: workflow start (one workflow per fact-check run)
- Temporal → Agent Service: activity dispatch, retry policies, timeouts
- Phase gating: sequential activities in Phase 1/3, parallel activities in Phase 2
- Completion tracking: Temporal knows when activities succeed or fail

**Redis Streams (data plane) handles:**
- Agent → Stream: observation publication (START, OBS, STOP)
- Agent → Stream: progress events for SSE relay (`progress:{runId}`)
- Backend ← Stream: progress consumption for SSE relay to frontend
- Asynchronous append/subscribe
- Append-only audit log

**Temporal does not handle:** streaming reasoning data, large observation payloads,
or real-time progress events (those flow through Redis Streams).

**Redis Streams does not handle:** task assignment, agent configuration,
retry policies, or phase gating (that stays on the Temporal control plane).

The two planes fail independently. If Temporal is down, agents cannot receive
new tasks but previously dispatched activities can continue publishing
observations. If Redis is down, agents cannot publish observations but
Temporal activities still report completion status.

---

## 2. Stream Lifecycle Phases

### Phase 0 — Stream Initialization

Triggered when the Temporal workflow dispatches the ingestion agent activity.
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

The Temporal activity completes, signaling the workflow to proceed to the
next step.

---

### Phase 1 — Sequential Processing

The Temporal workflow dispatches claim-detector and entity-extractor in
sequence as activities. Each agent:

1. Receives its task via Temporal activity dispatch
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

The Temporal workflow detects entity extraction activity has completed.
It simultaneously dispatches six agents as parallel activities:

- ClaimReview Matcher
- Coverage Agent Left
- Coverage Agent Center
- Coverage Agent Right
- Domain Evidence Agent
- Source Validator

Each parallel agent:
1. Opens its own stream with START (phase: `fanout`)
2. Reads entity observations from upstream streams via `getObservations()`
3. Calls external APIs (NewsAPI, Google Fact Check Tools, primary sources,
   Media Bias Fact Check)
4. Publishes observations to its own stream
5. Emits `F` or `X` terminal status
6. Closes its stream with STOP

Because each agent publishes to its own stream, there are no write
conflicts between parallel agents. Temporal tracks which activities have
completed and gates Phase 3 on all six finishing.

---

### Phase 3 — Blindspot Detection and Synthesis

The Temporal workflow detects that all six Phase 2 activities are complete.
It dispatches the blindspot detector:

1. Opens stream with START
2. Reads `COVERAGE_ARTICLE_COUNT` and `COVERAGE_FRAMING` observations
   from coverage agent streams via
   `getObservations(runId, { code: "COVERAGE_FRAMING" })`
3. Computes coverage asymmetry
4. Publishes `BLINDSPOT_SCORE`, `BLINDSPOT_DIRECTION`, and
   `CROSS_SPECTRUM_CORROBORATION` observations
5. Closes stream with STOP

Once the blindspot detector activity completes, the Temporal workflow
dispatches the synthesizer:

1. Opens stream with START (phase: `synthesis`)
2. Reads all observations across all agent streams via
   `getObservations(runId)` — this issues `XRANGE` on all 10 preceding
   agent streams
3. Applies observation resolution logic (DMN DetermineOBXResolution —
   latest `C` wins, then latest `F`, `X` excluded)
4. Computes `CONFIDENCE_SCORE` from weighted upstream signals
5. Maps confidence score to `VERDICT` coded value
6. Publishes `VERDICT_NARRATIVE` as `TX` type observation
7. Publishes all synthesis observations at `F` status
8. Closes stream with STOP

The run transitions to `completed`.

---

### Phase 4 — Publication

The NestJS backend reads the synthesized observations directly from Redis
Streams. No edge serialization adapter is needed — the observation format
is already JSON.

The backend:
1. Reads all `F` and `C` status observations for the run
2. Applies observation resolution (same logic as synthesizer)
3. Constructs the consumer-facing verdict response
4. Persists the verdict to PostgreSQL via TypeORM
5. Generates a static HTML snapshot and stores it on S3
6. Serves via REST API and SSE progress stream

The run transitions to `completed`. The session transitions to `frozen`.
The Redis Streams are retained as the audit record. The API response is
a projection of that record.

---

## 3. SSE Progress Relay

During a run, agents publish progress events to `progress:{runId}` in
Redis. The NestJS backend subscribes to this key and relays events to
the React frontend via Server-Sent Events (SSE).

Progress events include:
- Agent started / completed
- Phase transitions
- Observation counts
- Error notifications

This provides real-time visibility into run progress without exposing
Redis internals to the frontend.

---

## 4. Observation Growth Over a Full Run

A typical run produces approximately 65–85 observations across all 11 agents.

| Agent | Expected Observations | Codes |
|---|---|---|
| Ingestion | 3–5 | CLAIM_TEXT, CLAIM_SOURCE_URL, CLAIM_SOURCE_DATE, CLAIM_DOMAIN |
| Claim Detector | 2–3 | CHECK_WORTHY_SCORE, CLAIM_NORMALIZED |
| Entity Extractor | 4–12 | ENTITY_PERSON (xN), ENTITY_ORG (xN), ENTITY_DATE, ENTITY_LOCATION, ENTITY_STATISTIC |
| ClaimReview Matcher | 3–5 | CLAIMREVIEW_MATCH, CLAIMREVIEW_VERDICT, CLAIMREVIEW_SOURCE, CLAIMREVIEW_URL, CLAIMREVIEW_MATCH_SCORE |
| Coverage Left | 4 | COVERAGE_ARTICLE_COUNT, COVERAGE_FRAMING, COVERAGE_TOP_SOURCE, COVERAGE_TOP_SOURCE_URL |
| Coverage Center | 4 | Same codes, agent = coverage-center |
| Coverage Right | 4 | Same codes, agent = coverage-right |
| Domain Evidence | 4 | DOMAIN_SOURCE_NAME, DOMAIN_SOURCE_URL, DOMAIN_EVIDENCE_ALIGNMENT, DOMAIN_CONFIDENCE |
| Source Validator | 4 | SOURCE_EXTRACTED_URL, SOURCE_VALIDATION_STATUS, SOURCE_CONVERGENCE_SCORE, CITATION_LIST |
| Blindspot Detector | 3 | BLINDSPOT_SCORE, BLINDSPOT_DIRECTION, CROSS_SPECTRUM_CORROBORATION |
| Synthesizer | 4–6 | CONFIDENCE_SCORE, VERDICT, VERDICT_NARRATIVE, SYNTHESIS_SIGNAL_COUNT, SYNTHESIS_OVERRIDE_REASON |

`P` status observations are additional — agents may publish several
before promoting to `F`. The append-only log retains all of them.

---

## 5. Stream Identity and Correlation

The run ID (e.g. `claim-4821-run-003`) is the correlation key for the
entire lifecycle. It appears in:

- Redis Stream key prefix: `reasoning:{runId}:*`
- Every observation's `runId` field
- Every START/STOP message's `runId` field
- Temporal workflow ID
- PostgreSQL run record
- Backend API response as `runId` field

Any agent, at any point, can read the full observation state for a run
by querying `getObservations(runId)`. The `ReasoningStream` interface
handles fan-out across all agent streams for that run. No agent needs
to know which other agents exist — it reads observations by code, not
by agent.

---

## 6. Failure and Recovery

**Agent failure mid-run:**
Temporal detects activity failure via timeout or error return. Temporal's
built-in retry policy retries the activity up to 3 times with exponential
backoff. If the agent remains unreachable after retries, the workflow
marks the run as `ERROR`. Observations already published by other agents
are preserved in Redis Streams. The workflow can be restarted — it checks
which agent streams have STOP messages and re-dispatches only incomplete
agents.

**Backend restart:**
The NestJS backend is stateless with respect to run progress. On restart,
it queries PostgreSQL for active runs and re-subscribes to their
`progress:{runId}` streams in Redis to resume SSE relay.

**Temporal Server restart:**
Temporal persists workflow state durably. On restart, all in-progress
workflows resume from their last checkpoint. No run state is lost.

**Redis data loss:**
The observation log is the ground truth. Redis persistence must be
configured appropriately:
- **Development:** RDB snapshots at default intervals (acceptable loss)
- **Production:** ElastiCache with Multi-AZ replication and AOF with
  `appendfsync everysec`, or Kafka graduation (ADR-012) for durability
  guarantees

Backup strategy for Redis data is out of scope for the prototype but
must be addressed before any production deployment.
