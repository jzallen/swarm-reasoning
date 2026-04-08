# HL7v2 Message Lifecycle — hl7-agent-factchecker

**Version:** 0.1.0

This document explains how an HL7v2 message is created, grown, routed,
finalized, and serialized across a full fact-checking run. It is the
narrative companion to `c4-containers.mermaid` and `agent-topology.mermaid`.

---

## 1. Core Principle: Mirth is a Carrier, Not a Router

The most important architectural distinction in this system is that
**routing logic lives in the orchestrator, not in Mirth**.

Mirth Connect handles:
- HL7v2 message framing (MLLP)
- ACK/NACK generation and receipt
- Message delivery between named channels
- Edge serialization (HL7v2 → JSON) on the orchestrator's Mirth instance

Mirth does not handle:
- Deciding which agent receives which message
- Sequencing agents
- Fan-out logic
- Completion detection

The orchestrator's Mirth channel is a hub. Subagent Mirth instances are
endpoints. The orchestrator's LangGraph process decides where each message
goes and instructs its own Mirth instance via channel routing configuration
that the orchestrator updates at runtime.

If Mirth were the router, adding a new agent would require changing Mirth
channel configuration. Because the orchestrator is the router, adding a
new agent requires only registering it in the orchestrator's DAG config
and standing up a new bundle.

---

## 2. Message Lifecycle Phases

### Phase 0 — Message Initialization

Triggered when the orchestrator dispatches the ingestion agent via MCP.
The ingestion agent's tool layer creates a new message file in YottaDB:

```
^MSG("RUN-20260406-a3f7", "MSH", "sending_app")    = "ingestion-agent"
^MSG("RUN-20260406-a3f7", "MSH", "datetime")        = "20260406120000"
^MSG("RUN-20260406-a3f7", "MSH", "control_id")      = "RUN-20260406-a3f7-MSG001"
^MSG("RUN-20260406-a3f7", "PID", "claim_id")        = "CLAIM-20260406-001"
^MSG("RUN-20260406-a3f7", "PID", "claim_slug")      = "BidenVaccineMandate"
^MSG("RUN-20260406-a3f7", "PID", "claim_date")      = "20211104"
```

The first OBX rows are written at `P` status:

```
^MSG("RUN-20260406-a3f7", "OBX", 1, "code")         = "CLAIM_TEXT"
^MSG("RUN-20260406-a3f7", "OBX", 1, "value")        = "Biden issued a federal vaccine mandate..."
^MSG("RUN-20260406-a3f7", "OBX", 1, "status")       = "P"
^MSG("RUN-20260406-a3f7", "OBX", 1, "observer")     = "ingestion-agent"
```

The agent then promotes to `F` once the claim is validated and registered:

```
^MSG("RUN-20260406-a3f7", "OBX", 2, "code")         = "CLAIM_TEXT"
^MSG("RUN-20260406-a3f7", "OBX", 2, "value")        = "Biden issued a federal vaccine mandate..."
^MSG("RUN-20260406-a3f7", "OBX", 2, "status")       = "F"
^MSG("RUN-20260406-a3f7", "OBX", 2, "observer")     = "ingestion-agent"
```

The ingestion agent's Mirth instance serializes the YottaDB globals into
a pipe-delimited HL7v2 string and delivers it to the orchestrator's
inbound Mirth channel over MLLP. The orchestrator receives the ACK.

---

### Phase 1 — Sequential Processing

The orchestrator dispatches claim-detector and entity-extractor in
sequence via MCP. Each agent:

1. Receives its task via MCP tool call
2. Reads existing OBX rows from its YottaDB via `get_observations()`
3. Reasons and calls `add_observation()` tools, which write to YottaDB
4. Emits `F` status rows when complete
5. Mirth delivers the updated message to the orchestrator

The OBX sequence counter increments monotonically across all agents.
By the end of Phase 1, the message contains OBX rows 1–N covering
`CLAIM_TEXT`, `CLAIM_SOURCE_*`, `CHECK_WORTHY_SCORE`, `CLAIM_NORMALIZED`,
and all `ENTITY_*` codes.

---

### Phase 2 — Parallel Fan-Out

The orchestrator detects that entity extraction is complete (all
`ENTITY_*` codes have `F` status rows). It simultaneously dispatches
five agents via MCP:

- ClaimReview Matcher → push pattern, channel `CR_IN`
- Coverage Agent Left → push pattern, channel `COV_L_IN`
- Coverage Agent Center → push pattern, channel `COV_C_IN`
- Coverage Agent Right → push pattern, channel `COV_R_IN`
- Domain Evidence Agent → push pattern, channel `DOM_IN`

Each parallel agent:
1. Reads entity data via `get_observations()` — pull pattern used here
   if the agent needs YottaDB data from a prior agent's instance
2. Calls external APIs (NewsAPI, Google Fact Check Tools, primary sources)
3. Writes OBX rows to its own YottaDB
4. Emits `F` or `X` terminal status
5. Mirth delivers ACK + message to orchestrator

Because each agent appends to its own YottaDB with sequentially
increasing OBX numbers (each bundle maintains its own counter,
reconciled by the orchestrator into the master message), there are no
write conflicts between parallel agents.

The orchestrator's completion register tracks which of the five parallel
agents have emitted terminal status. It does not proceed to Phase 3
until all five have done so.

---

### Phase 3 — Blindspot Detection

The orchestrator detects that the three coverage agents are all complete.
It dispatches the blindspot detector, which:

1. Uses pull pattern: requests `COVERAGE_ARTICLE_COUNT` and
   `COVERAGE_FRAMING` OBX rows from coverage agents via orchestrator
2. Computes coverage asymmetry
3. Writes `BLINDSPOT_SCORE`, `BLINDSPOT_DIRECTION`, and
   `CROSS_SPECTRUM_CORROBORATION` OBX rows
4. Emits `F` terminal status

---

### Phase 4 — Synthesis

The orchestrator detects all nine preceding agents have emitted terminal
status. It dispatches the synthesizer:

1. Synthesizer calls `get_observations(claim_id)` — retrieves all OBX
   rows across all agents via the orchestrator's MCP routing
2. Applies OBX resolution logic (DMN DetermineOBXResolution — latest
   `C` wins, then latest `F`, `X` excluded)
3. Computes `CONFIDENCE_SCORE` from weighted upstream signals
4. Maps confidence score to `VERDICT` coded value
5. Writes `VERDICT_NARRATIVE` as `TX` type OBX
6. Emits all synthesis OBX rows at `F` status
7. Mirth delivers to orchestrator

The run transitions to `SYNTHESIZED`.

---

### Phase 5 — Edge Serialization

The orchestrator's Mirth instance detects a `SYNTHESIZED` run via its
channel filter (checks for a `VERDICT` `F` status OBX row). The edge
serialization channel transformer:

1. Reads all `F` and `C` status OBX rows for the run from YottaDB
2. Maps OBX codes to JSON field names using `obx-code-registry.json`
3. Assembles a FHIR-like JSON object
4. POSTs to the configured consumer endpoint

The run transitions to `PUBLISHED`. The raw HL7v2 message and YottaDB
globals are retained as the audit record. The JSON is the consumer-facing
projection of that record.

---

## 3. Message Growth Over a Full Run

A typical run produces approximately 60–80 OBX rows across all agents.
The table below shows the expected OBX distribution:

| Agent | Expected OBX rows | Codes |
|---|---|---|
| Ingestion | 3–5 | CLAIM_TEXT, CLAIM_SOURCE_URL, CLAIM_SOURCE_DATE, CLAIM_DOMAIN |
| Claim Detector | 2–3 | CHECK_WORTHY_SCORE, CLAIM_NORMALIZED |
| Entity Extractor | 4–12 | ENTITY_PERSON (×N), ENTITY_ORG (×N), ENTITY_DATE, ENTITY_LOCATION, ENTITY_STATISTIC |
| ClaimReview Matcher | 3–5 | CLAIMREVIEW_MATCH, CLAIMREVIEW_VERDICT, CLAIMREVIEW_SOURCE, CLAIMREVIEW_URL, CLAIMREVIEW_MATCH_SCORE |
| Coverage Left | 4 | COVERAGE_ARTICLE_COUNT, COVERAGE_FRAMING, COVERAGE_TOP_SOURCE, COVERAGE_TOP_SOURCE_URL |
| Coverage Center | 4 | Same codes, OBX.16 = coverage-center |
| Coverage Right | 4 | Same codes, OBX.16 = coverage-right |
| Blindspot Detector | 3 | BLINDSPOT_SCORE, BLINDSPOT_DIRECTION, CROSS_SPECTRUM_CORROBORATION |
| Domain Evidence | 4 | DOMAIN_SOURCE_NAME, DOMAIN_SOURCE_URL, DOMAIN_EVIDENCE_ALIGNMENT, DOMAIN_CONFIDENCE |
| Synthesizer | 4–6 | CONFIDENCE_SCORE, VERDICT, VERDICT_NARRATIVE, SYNTHESIS_SIGNAL_COUNT, SYNTHESIS_OVERRIDE_REASON |

`P` status rows are additional — agents may emit several before
promoting to `F`. The append-only log retains all of them.

---

## 4. Message Identity and Correlation

The run ID (`RUN-{date}-{uuid}`) is the correlation key for the entire
lifecycle. It appears in:

- YottaDB global subscript: `^MSG(run_id, ...)`
- HL7v2 MSH.10 message control ID prefix
- ACK log: `^ACK_LOG(run_id, ...)`
- Mirth channel routing metadata
- Final JSON payload as `run_id` field

Any agent, at any point, can reconstruct the full message state by
reading `^MSG(run_id, "OBX", ...)` via the orchestrator's
`get_observations()` MCP tool. No agent needs to receive the full
message text to operate — it reads only what it needs, when it needs it.

---

## 5. Failure and Recovery

**Agent failure mid-run:**
The orchestrator detects a missing ACK after a configurable timeout.
It retries the MCP dispatch up to 3 times. If the agent remains
unreachable, the run is marked `ERROR` and retained. OBX rows already
written by other agents are preserved in YottaDB. The run can be
resumed once the failed agent bundle is restored — the orchestrator
reads current completion state via `get_terminal_status()` and
re-dispatches only incomplete agents.

**Orchestrator restart:**
The orchestrator is stateless (ADR-010). On restart, it reads `^RUN`
globals to find in-progress runs, calls `get_terminal_status()` on each
registered agent to reconstruct the completion register, and resumes
from the correct phase.

**YottaDB volume loss:**
The append-only OBX log is the ground truth. YottaDB volume persistence
must be configured in the Docker Compose volume definitions. Volume
backup strategy is out of scope for the prototype but must be addressed
before any production deployment.
