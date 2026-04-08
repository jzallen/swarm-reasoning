# Non-Functional Requirements — hl7-agent-factchecker

**Version:** 0.1.0
**Framework:** ISO/IEC 25010 quality characteristics
**Format:** Quality Attribute Scenarios (QAS) with Planguage supplementary
attributes where applicable.

Each NFR is numbered, assigned to an ISO/IEC 25010 category, and expressed
as a scenario with stimulus, environment, response, and response measure.

---

## Category 1 — Performance Efficiency

### NFR-001: End-to-end run latency

**Characteristic:** Time behaviour
**Quality Attribute Scenario:**
- **Stimulus:** Operator submits a check-worthy claim via POST /claims
- **Environment:** Normal operation, all 10 agent bundles healthy, external APIs reachable
- **Response:** System processes the claim to PUBLISHED state
- **Response Measure:** Elapsed time from POST acceptance to PUBLISHED status is under 120 seconds

**Planguage:**
```
Ambition: 90 seconds
Threshold: 120 seconds
Fail: > 180 seconds
```

**Notes:** The parallel fan-out phase (agents 4–7 + 9) is the primary latency
driver. External API response times (NewsAPI, Google Fact Check, MBFC) are
outside system control. LLM call latency per agent is bounded by model and
prompt size.

---

### NFR-002: Parallel fan-out phase latency

**Characteristic:** Time behaviour
**Quality Attribute Scenario:**
- **Stimulus:** Orchestrator dispatches the five parallel agents simultaneously
- **Environment:** Normal operation
- **Response:** All five agents emit terminal OBX status
- **Response Measure:** All five agents complete within 45 seconds of dispatch

---

### NFR-003: MCP round-trip latency

**Characteristic:** Time behaviour
**Quality Attribute Scenario:**
- **Stimulus:** Orchestrator issues a get_observations MCP tool call to a subagent
- **Environment:** Normal operation, agent bundle healthy, data present in YottaDB
- **Response:** Agent MCP server returns OBX rows
- **Response Measure:** P99 latency under 500ms for queries returning fewer than 100 OBX rows

---

### NFR-004: OBX write throughput

**Characteristic:** Resource utilisation
**Quality Attribute Scenario:**
- **Stimulus:** Multiple agents write OBX rows concurrently during parallel fan-out
- **Environment:** Peak load — 5 agents writing concurrently
- **Response:** All OBX rows are persisted correctly with unique sequence numbers
- **Response Measure:** Zero duplicate OBX sequence numbers across 1000 consecutive runs in load testing

---

## Category 2 — Reliability

### NFR-005: Agent idempotency

**Characteristic:** Fault tolerance
**Quality Attribute Scenario:**
- **Stimulus:** Orchestrator dispatches the same agent task twice for the same run_id (e.g., due to ACK timeout and retry)
- **Environment:** Any agent bundle
- **Response:** Agent detects duplicate dispatch and does not write additional OBX rows
- **Response Measure:** OBX row count for the run is identical before and after the duplicate dispatch

**Implementation note:** Agents check for existing F-status rows for their
owned codes before writing. If F-status rows already exist for the run_id,
the task is treated as a no-op and an ACK AA is returned.

---

### NFR-006: Mirth ACK retry behaviour

**Characteristic:** Fault tolerance
**Quality Attribute Scenario:**
- **Stimulus:** Orchestrator Mirth receives ACK AE from an agent Mirth instance
- **Environment:** Transient agent error
- **Response:** Orchestrator retries message delivery
- **Response Measure:** Up to 3 retries with 5-second backoff before escalation to error log

---

### NFR-007: Orchestrator restart recovery

**Characteristic:** Recoverability
**Quality Attribute Scenario:**
- **Stimulus:** Orchestrator process terminates unexpectedly during an active run
- **Environment:** Run in ANALYZING state with partial agent completion
- **Response:** Orchestrator restarts and reconstructs completion state from agent MCP tool calls
- **Response Measure:** Run resumes correctly within 30 seconds of orchestrator restart, with no duplicate agent dispatches and no data loss in agent YottaDB instances

---

### NFR-008: YottaDB transaction isolation for concurrent OBX writes

**Characteristic:** Fault tolerance
**Quality Attribute Scenario:**
- **Stimulus:** Two agents attempt to write OBX rows with the same sequence number due to a race condition
- **Environment:** Parallel fan-out phase
- **Response:** YottaDB ACID transaction guarantees only one write succeeds; the other retries with the next available sequence number
- **Response Measure:** Zero OBX sequence number collisions in the YottaDB log across all runs

---

### NFR-009: Append-only log integrity

**Characteristic:** Integrity
**Quality Attribute Scenario:**
- **Stimulus:** Any process (agent, orchestrator, test harness) attempts to modify or delete an existing OBX row
- **Environment:** Any
- **Response:** The operation is rejected
- **Response Measure:** No existing OBX row is modified or deleted after initial write; verified by comparing YottaDB snapshots before and after a full run

---

## Category 3 — Security

### NFR-010: MCP connections are internal-network-only

**Characteristic:** Confidentiality
**Quality Attribute Scenario:**
- **Stimulus:** An external actor attempts to connect to a subagent MCP server
- **Environment:** Production Docker network
- **Response:** Connection is refused
- **Response Measure:** Agent MCP server ports are not exposed outside the Docker internal network; verified by network scan from outside the Docker network

---

### NFR-011: PII sanitization before LLM calls

**Characteristic:** Confidentiality
**Quality Attribute Scenario:**
- **Stimulus:** A claim text containing a named individual and a date of birth is submitted
- **Environment:** Normal operation
- **Response:** The prompt sent to the LLM provider does not contain the raw date of birth
- **Response Measure:** Zero raw PII fields (SSN, DOB, financial identifiers) present in LLM prompt payloads in log analysis across the validation corpus

---

### NFR-012: External API responses are validated before OBX write

**Characteristic:** Integrity
**Quality Attribute Scenario:**
- **Stimulus:** An external API (NewsAPI, MBFC, GFCT) returns a malformed or unexpectedly large response
- **Environment:** Agent executing a coverage or domain evidence task
- **Response:** Agent validates the response before passing it to the tool layer for OBX writing
- **Response Measure:** No malformed external API response causes an invalid OBX row to be written to YottaDB; verified by injecting malformed responses in integration tests

---

### NFR-013: HL7v2 messages are confined to the internal Docker network

**Characteristic:** Confidentiality
**Quality Attribute Scenario:**
- **Stimulus:** An HL7v2 message containing claim text is in transit between agent Mirth and orchestrator Mirth
- **Environment:** Normal operation
- **Response:** Message is transmitted only on the internal Docker network
- **Response Measure:** No MLLP traffic is observable outside the Docker bridge network; verified by packet capture on the host network interface

---

## Category 4 — Maintainability

### NFR-014: New agent bundle can be added without modifying existing agents

**Characteristic:** Modifiability
**Quality Attribute Scenario:**
- **Stimulus:** A new specialist agent (e.g., a scientific literature agent) is added to the system
- **Environment:** Development
- **Response:** The new agent is registered in the orchestrator DAG and OBX code registry; no existing agent code is modified
- **Response Measure:** Zero existing agent files modified when adding a new agent, verified by git diff

---

### NFR-015: New OBX code can be added without schema migration

**Characteristic:** Modifiability
**Quality Attribute Scenario:**
- **Stimulus:** A new observation code is added to obx-code-registry.json
- **Environment:** Development
- **Response:** The new code is available to agents at runtime without restarting YottaDB or running a migration script
- **Response Measure:** New code is usable within one orchestrator restart; no migration script required

---

### NFR-016: Mirth channel configuration is version-controlled

**Characteristic:** Analysability
**Quality Attribute Scenario:**
- **Stimulus:** A developer needs to audit a routing change made two weeks ago
- **Environment:** Version control system
- **Response:** Mirth channel XML exports are committed in the repository
- **Response Measure:** All Mirth channel configurations exist as committed XML files in the repository; no Mirth configuration exists only in the Mirth admin console

---

## Category 5 — Portability

### NFR-017: Full local stack runs via a single Docker Compose command

**Characteristic:** Installability
**Quality Attribute Scenario:**
- **Stimulus:** A developer clones the repository on a machine with Docker installed
- **Environment:** macOS or Linux, Docker 24+, 16GB RAM
- **Response:** All containers start and the system accepts a test claim submission
- **Response Measure:** `docker compose up --profile dev` completes without error and a test claim reaches PUBLISHED state within 5 minutes of first startup

---

### NFR-018: YottaDB runs in Docker on macOS

**Characteristic:** Adaptability
**Quality Attribute Scenario:**
- **Stimulus:** A developer on macOS attempts to run a YottaDB container
- **Environment:** macOS with Docker Desktop (Linux VM)
- **Response:** YottaDB starts and accepts Python API connections
- **Response Measure:** YottaDB Docker container starts without error on macOS; confirmed by running the Python yottadb test suite against the container

---

## Category 6 — Correctness (Validation-specific)

### NFR-019: Swarm verdict accuracy on PolitiFact corpus

**Characteristic:** Functional correctness
**Quality Attribute Scenario:**
- **Stimulus:** The 50-claim PolitiFact validation corpus is processed
- **Environment:** Normal operation, all external APIs reachable
- **Response:** System produces verdicts for all 50 claims
- **Response Measure:** Correct alignment rate (system verdict within one tier of PolitiFact verdict) is at least 70% across all 50 claims

**Planguage:**
```
Ambition: 80% correct alignment
Threshold: 70% correct alignment
Fail: < 60% correct alignment
```

---

### NFR-020: Swarm outperforms single-agent on non-indexed claims

**Characteristic:** Functional correctness
**Quality Attribute Scenario:**
- **Stimulus:** The 10 non-ClaimReview-indexed claims from the corpus are processed by both the swarm and a single-agent baseline
- **Environment:** Normal operation
- **Response:** Swarm correct alignment rate exceeds single-agent baseline
- **Response Measure:** Swarm correct alignment rate on non-indexed claims exceeds single-agent baseline by at least 20 percentage points

---

### NFR-021: SYNTHESIS_SIGNAL_COUNT accurately reflects evidence breadth

**Characteristic:** Functional correctness
**Quality Attribute Scenario:**
- **Stimulus:** A claim is processed with all 10 agents active
- **Environment:** Normal operation, all external APIs returning data
- **Response:** Synthesizer records the number of F/C status OBX rows used as inputs
- **Response Measure:** SYNTHESIS_SIGNAL_COUNT matches the actual count of F/C status rows included in the synthesizer's consolidated OBX log, verified for all 50 corpus claims

---

## Category 7 — Auditability

### NFR-022: Every published verdict has a traceable audit log

**Characteristic:** Accountability
**Quality Attribute Scenario:**
- **Stimulus:** An analyst disputes a published verdict for run "RUN-001"
- **Environment:** Post-publication
- **Response:** The analyst retrieves the raw HL7v2 audit log and identifies the specific OBX rows that determined the verdict
- **Response Measure:** The audit_log_ref in every published verdict resolves to a retained .hl7 file; the file contains OBX rows from at least 8 distinct agents with OBX.16 attribution

---

### NFR-023: Correction history is preserved in the audit log

**Characteristic:** Non-repudiation
**Quality Attribute Scenario:**
- **Stimulus:** An agent emits a C-status correction overriding a prior F-status observation
- **Environment:** Any run
- **Response:** Both the original F row and the correction C row are present in the YottaDB log
- **Response Measure:** Zero original F rows are absent from the log when a corresponding C row exists; verified across the validation corpus

---

## Category 8 — Observability

### NFR-024: Run status is queryable at any point during processing

**Characteristic:** Operability
**Quality Attribute Scenario:**
- **Stimulus:** An operator polls GET "/runs/{run_id}" during an active run
- **Environment:** Run in ANALYZING state
- **Response:** API returns current status and completion register summary
- **Response Measure:** GET "/runs/{run_id}" responds within 500ms with current status, number of agents complete, and number of agents pending; available at all lifecycle states

---

### NFR-025: Agent heartbeat is monitored by orchestrator

**Characteristic:** Fault tolerance
**Quality Attribute Scenario:**
- **Stimulus:** An agent bundle becomes unresponsive during a run
- **Environment:** Parallel fan-out phase
- **Response:** Orchestrator detects absence of heartbeat and marks the agent as ERROR
- **Response Measure:** Orchestrator detects agent heartbeat failure within 30 seconds; run transitions to an error state with the unresponsive agent identified; no run hangs indefinitely

---

### NFR-026: OBX log is queryable for post-run analysis

**Characteristic:** Analysability
**Quality Attribute Scenario:**
- **Stimulus:** A data analyst wants to retrieve all BLINDSPOT_SCORE observations above 0.7 across all published runs
- **Environment:** Post-publication, YottaDB loaded with completed runs
- **Response:** Query returns matching OBX rows with run_id attribution
- **Response Measure:** YottaDB $ORDER prefix scan on ^MSG(*,"OBX",*,"code") = "BLINDSPOT_SCORE" completes in under 2 seconds for a corpus of 50 completed runs

---

### NFR-027: Mirth channel errors surface in the run error log

**Characteristic:** Operability
**Quality Attribute Scenario:**
- **Stimulus:** A Mirth channel experiences a delivery failure (AE or AR ACK)
- **Environment:** Any phase of a run
- **Response:** The error is recorded in the run error log with run_id, message_control_id, agent, ACK code, and timestamp
- **Response Measure:** 100% of AE and AR ACK events appear in the run error log within 5 seconds of receipt; verified by injecting deliberate Mirth failures in integration tests
