# Architecture Decision Records — hl7-agent-factchecker

Architecture Decision Records (ADRs) document significant design choices,
the context that drove them, the options considered, and the rationale for
the decision made. They are written at decision time and never retroactively
revised — superseded ADRs are marked as such and linked to their replacement.

---

## ADR-001: HL7v2 as inter-agent wire format over JSON

**Status:** Accepted
**Date:** 2026-04

### Context

A multi-agent fact-checking pipeline requires a shared wire format that
agents can read, append to, and pass between one another. The format must
support hierarchical data, streaming delivery, partial reads, epistemic
status signaling, and provenance tracking. The two primary candidates were
JSON and HL7v2 pipe-delimited messaging.

JSON is the dominant interchange format in modern API design and is well
understood. However, JSON requires complete structural validity to be
parseable — a missing closing bracket corrupts the entire document. LLMs
generating JSON must maintain structural context across tokens, leading to
higher error rates on deeply nested schemas. JSON also has no native concept
of result status, acknowledgment, or message provenance.

HL7v2 is a pipe-delimited line-oriented format where each segment is
self-contained and independently parseable. A single malformed segment does
not corrupt adjacent segments. The format includes native fields for result
status (`P` preliminary, `F` final, `C` corrected, `X` cancelled),
sending application identity, message timestamp, and acknowledgment
semantics. It was designed for streaming delivery over TCP. HL7v2 is
natively stored in MUMPS/YottaDB globals without a serialization gap.

### Options Considered

**Option A — JSON**
Standard format with excellent tooling, universal library support, and
familiarity. Structurally fragile for LLM generation. No native epistemic
status. No native acknowledgment. Requires additional conventions to carry
provenance.

**Option B — HL7v2 pipe-delimited (chosen)**
Line-oriented, self-delimiting, natively streamable. OBX segments carry
typed key-value observations with result status, units, reference range,
and observation identity built into the segment structure. MSH segment
carries message provenance. ACK/NACK semantics are part of the standard.
Natively maps to YottaDB global subscript structure.

**Option C — TOML**
Hierarchical, locally valid at the section level, better tooling than HL7v2.
No native epistemic status. Not streamable. No acknowledgment semantics.
Not natively aligned with MUMPS storage.

### Decision

Option B. The combination of line-level validity, native result status
semantics, streaming design, acknowledgment protocol, and direct alignment
with YottaDB storage makes HL7v2 the most architecturally coherent choice
for this system. The healthcare toolchain has solved problems — message
contracts, epistemic state, audit trails — that the broader data engineering
world keeps rediscovering. The format is not used because this is a
healthcare project; it is used because the data model genuinely fits.

LLMs in this system never generate raw HL7v2 strings. They call tools that
produce valid segments (see ADR-004). The format's complexity is therefore
encapsulated in the tool layer, not exposed to the model.

### Consequences

- All inter-agent data must be expressible as typed OBX observations.
  Relational or graph-structured findings require flattening to OBX rows
  by convention (see `hl7-segment-spec.md`).
- Every team member must understand the OBX segment structure and the
  project's OBX code registry (see `obx-code-registry.json`).
- Edge consumers receive JSON, not HL7v2. A serialization adapter is
  required at every system boundary facing non-agent consumers (see ADR-006).
- HL7v2 escape sequences (`\F\`, `\S\`, `\R\`, `\E\`, `\T\`) must be
  applied consistently when field values contain delimiter characters.

---

## ADR-002: YottaDB over relational or document databases for agent state

**Status:** Accepted
**Date:** 2026-04

### Context

Each agent bundle requires local storage for the reasoning state it
accumulates and reads during a fact-checking run. The storage layer must
support: append-only writes of OBX-structured observations, prefix-scan
queries over agent-scoped key ranges, ACID transactions for atomic OBX
batch writes, and low operational overhead per agent container.

Relational databases (PostgreSQL, SQLite) offer strong query capabilities
but impose a fixed schema that must be migrated when new OBX codes are
introduced. Document databases (MongoDB) are schemaless but add operational
complexity and have no native affinity with the HL7v2 data model.

YottaDB is an open-source MUMPS database. Its native storage model is a
hierarchical key-value trie (globals) where subscripts are the keys and
leaves are string values. This structure maps directly to the HL7v2 OBX
segment: message ID, segment index, and field name become subscripts;
field values become leaves. No serialization gap exists between the wire
format and storage format.

### Options Considered

**Option A — PostgreSQL**
Strong ACID guarantees, rich query language, excellent tooling. Requires
schema definition and migration for every new OBX code. JSON/JSONB columns
can store variable OBX structures but lose type safety and index efficiency.
Heavyweight for a per-agent container deployment.

**Option B — SQLite**
Lightweight, embeddable, no separate process. Same schema rigidity as
PostgreSQL. Less suitable for concurrent multi-agent writes against a
shared file. Adequate for single-agent local storage but awkward for
the append-only streaming model.

**Option C — YottaDB (chosen)**
Natively stores HL7v2 globals without a serialization layer. Key schema
mirrors OBX structure directly:
```
^MSG(claim_id, "OBX", seq, "code")   = "CTR"
^MSG(claim_id, "OBX", seq, "value")  = "1.96"
^MSG(claim_id, "OBX", seq, "status") = "P"
```
Adding a new OBX code requires zero schema changes. `$ORDER` function
enables efficient trie traversal for prefix scans. ACID transactions
wrap atomic OBX batch writes. Lightweight enough for a per-bundle
container. Free and open source (GPL v3).

**Option D — Redis**
Fast key-value store with good streaming support. No native trie traversal.
Persistence model requires explicit configuration. No MUMPS alignment.

### Decision

Option C. The absence of a serialization gap between HL7v2 wire format and
YottaDB storage is the decisive factor. The system's data model is defined
once — in the OBX segment structure and the OBX code registry — and that
same model is used for transport, storage, and query without translation.
Schema rigidity is replaced by the OBX code registry as the governing
contract, which is a document rather than a migration.

### Consequences

- Engineers must understand YottaDB global key design before writing
  agent code. A poor key schema is difficult to refactor. The global
  key schema must be defined in `erd-full.mermaid` before agent
  implementation begins.
- YottaDB's `$ORDER`-based iteration is idiomatic for prefix scans but
  unfamiliar to engineers with only relational backgrounds. A thin Python
  wrapper (`yottadb` pip package) abstracts the M API.
- Each agent bundle runs its own YottaDB instance. Cross-agent reads
  happen via MCP tool calls to the orchestrator, not direct database
  connections (see ADR-010).
- YottaDB runs on Linux only. macOS development requires Docker.

---

## ADR-003: Append-only OBX log over mutable shared state

**Status:** Accepted
**Date:** 2026-04

### Context

As agents contribute findings to a fact-checking run, the collective
reasoning state grows. A design choice exists between mutable shared state
(agents overwrite or update a central record) and an append-only log
(agents add new OBX rows; earlier rows are never modified).

Mutable shared state simplifies the final read — there is always one
current value per field. However, it destroys the history of how the
system's confidence evolved, makes concurrent writes conflict-prone,
and prevents attribution of which agent asserted what at which point.

An append-only log preserves the full reasoning trajectory. Corrections
are expressed as new OBX rows with `C` (corrected) status referencing
the original observation, not as overwrites. The synthesizer reads the
full log and resolves the current authoritative value by status and
sequence.

### Options Considered

**Option A — Mutable shared record**
Simple final state. Loses reasoning history. Concurrent write conflicts
require locking. No attribution. Not suitable for audit or interpretability
requirements.

**Option B — Append-only OBX log (chosen)**
Preserves full reasoning trajectory. Each agent contribution is attributed
via MSH sending application field. Corrections are first-class events.
YottaDB sequential subscripts (`^MSG(id,"OBX",1,...)` through
`^MSG(id,"OBX",N,...)`) implement this naturally. Delta Lake provides
a secondary append-only store for cross-run analytics if needed.

### Decision

Option B. The append-only log is the primary source of the system's
interpretability claim. The audit trail — which agent introduced a
finding, which agent corrected it, how confidence evolved from `P` to
`F` — is only possible if history is preserved. This is also the patient
chart mental model: a chart is never overwritten, only annotated.

### Consequences

- The synthesizer must implement log resolution logic: given multiple
  OBX rows for the same observation code, determine the authoritative
  current value by selecting the most recent `F` or `C` status row.
- YottaDB storage grows monotonically per run. Compaction or archival
  policy is required for long-running deployments but is out of scope
  for the prototype.
- Query patterns must account for log structure. "What is the current
  CTR confidence score?" requires a scan of all CTR OBX rows and
  selection of the latest authoritative one, not a simple key lookup.

---

## ADR-004: Tool-based HL7v2 construction over LLM-generated strings

**Status:** Accepted
**Date:** 2026-04

### Context

Agents must produce valid HL7v2 OBX segments as part of their output.
Two approaches exist: the LLM generates raw HL7v2 strings directly, or
the LLM calls structured tools that produce valid segments internally.

LLM generation of structured formats is a known failure mode. JSON
generation errors are well-documented; pipe-delimited formats with
positional field semantics, escape sequences, and delimiter conventions
are no easier. A single malformed OBX segment can corrupt downstream
parsing even though HL7v2 is line-oriented, if field counts or
component separators are wrong.

Tool-based construction moves structural responsibility to deterministic
code. The LLM decides *what* to assert; the tool decides *how* to
serialize it. The LLM's two failure modes — structural errors and
semantic errors — are separated. Structural errors become impossible.
Semantic errors (wrong interpretation) remain, but they are recoverable
and auditable.

### Options Considered

**Option A — LLM generates raw HL7v2 strings**
No tool layer required. High error rate on field positioning, escape
sequences, and delimiter conventions. Structural errors corrupt the
pipeline silently or noisily.

**Option B — Tool-based construction (chosen)**
LLM calls `add_observation(code, value, units, range, status)`.
Tool validates inputs, applies escape sequences, constructs the OBX
segment, writes to YottaDB, and returns a structured confirmation.
LLM cannot produce a malformed segment.

### Decision

Option B. The tool surface is small and stable:

```python
create_message(source, destination, event_type)
set_entity(id, name, timestamp)
add_observation(code, value, units, range, status)
add_note(text)
finalize_message() -> hl7_string
```

Structural correctness is guaranteed by the tool layer. The LLM's
role is limited to deciding which tools to call and with what values —
which is exactly what LLMs are reliable at.

### Consequences

- Every new OBX code must be registered in `obx-code-registry.json`
  before agents can use it. The tool validates codes against the
  registry at write time and rejects unknown codes.
- Tool implementations must handle all HL7v2 escape sequences
  correctly. This is a one-time implementation cost, not an ongoing
  LLM reliability risk.
- The tool layer is the appropriate place to enforce OBX code
  ownership — only the agent registered as the owner of a given
  code can write it.

---

## ADR-005: OBX result status as epistemic state carrier

**Status:** Accepted
**Date:** 2026-04

### Context

In a multi-agent pipeline where findings evolve over time, downstream
agents need to know whether an upstream observation is a hypothesis,
a confirmed finding, a correction of an earlier finding, or a
retraction. This epistemic state must be structural — carried in the
data, not inferred from prose — so that agents can act on it
programmatically.

HL7v2's OBX segment includes a result status field (OBX.11) with
standardized values. This field was designed for exactly this purpose
in clinical observation reporting and maps cleanly to the epistemic
states required in a reasoning pipeline.

### Decision

OBX.11 result status values are mapped to epistemic states as follows:

| HL7v2 Status | Meaning in this system |
|---|---|
| `P` | Preliminary — hypothesis or initial finding, not yet corroborated |
| `F` | Final — confirmed finding, agent considers this settled |
| `C` | Corrected — supersedes an earlier observation of the same code |
| `X` | Cancelled — claim determined not check-worthy or finding retracted |

The synthesizer treats only `F` and `C` status rows as authoritative
inputs to the final verdict. `P` rows are informational and may
indicate areas requiring further investigation. `X` rows are excluded
from synthesis but retained in the log for auditability.

### Consequences

- Agents must set status deliberately. Emitting `F` status is a
  commitment that the finding is settled from that agent's perspective.
  The synthesizer may override via a `C` row, but the original `F`
  remains in the log.
- The orchestrator uses status as a completion signal: when all
  expected agents have emitted at least one `F` or `X` row for their
  assigned observation codes, the run is eligible for synthesis.
- `P` status rows from parallel agents may temporarily contradict one
  another. This is expected and resolved by the synthesizer, not
  treated as an error.

---

## ADR-006: Edge serialization to JSON via Mirth adapter

**Status:** Accepted
**Date:** 2026-04

### Context

Downstream consumers — dashboards, REST API clients, analyst tools —
expect JSON. They should not need to understand HL7v2 segment structure,
OBX field positions, or the project's OBX code registry. The system
must present a clean JSON interface at its boundary while using HL7v2
internally.

A serialization adapter transforms finalized HL7v2 messages into
FHIR-like JSON at the edge. This adapter is the only place in the
system where HL7v2 is translated to JSON. All internal agent
communication remains on the HL7v2/YottaDB plane.

### Decision

Mirth Connect serves as the edge serialization adapter. A dedicated
Mirth channel on the orchestrator's Mirth instance subscribes to
finalized messages (those containing a synthesizer `F` status verdict
OBX row). The channel's transformer maps OBX rows to a JSON object
using the OBX code registry as the field name mapping. The output is
posted to a configurable HTTP destination.

The JSON structure is FHIR-like but not strictly FHIR-compliant.
Strict FHIR R4 compliance is out of scope for the prototype but the
structure is designed to be promotable to FHIR with minimal rework.

### Consequences

- The edge JSON schema must be documented and versioned independently
  of the internal HL7v2 message spec.
- Mirth's JavaScript transformer (Rhino engine) is the implementation
  language for the serialization logic. Rhino is old and slow; this
  is acceptable because serialization is not on the hot path.
- If Mirth Connect proves operationally burdensome, the adapter can
  be replaced with a Python script using the `hl7apy` library without
  changing any agent or YottaDB code.

---

## ADR-007: Mirth Connect as HL7v2 transport layer

**Status:** Accepted
**Date:** 2026-04

### Context

HL7v2 messages must be routed between agent bundles. A transport layer
is needed that understands HL7v2 framing, handles ACK/NACK semantics,
and can deliver messages reliably between containers. Options include
building a custom transport, using a general-purpose message broker
(Kafka, RabbitMQ), or using a purpose-built HL7v2 integration engine.

Mirth Connect is an open-source HL7 integration engine with native
support for HL7v2 framing (MLLP), ACK/NACK processing, channel-based
routing, JavaScript transformers, and a wide range of connectors.
It was designed specifically for the message patterns this system uses.

### Decision

Each agent bundle includes a Mirth Connect instance. The orchestrator's
Mirth instance is the routing hub. Subagent Mirth instances handle
inbound message receipt and outbound ACK. The orchestrator decides
routing targets; subagent Mirth instances do not route to one another
(see ADR-009).

Mirth Connect is not a DAG orchestrator. It is a carrier and transformer.
Routing logic — which agent receives which message, in what order —
lives in the orchestrator process, not in Mirth channel configuration.

### Consequences

- Each agent bundle adds a Mirth Connect container to its composition.
  This is non-trivial operational overhead for a prototype. The
  Docker Compose configuration must expose Mirth's admin port only
  on the internal Docker network.
- Mirth's channel configuration is XML-based and not easily
  version-controlled as code. Channel definitions should be exported
  and committed to the repository.
- Mirth Connect's community edition is free. Enterprise features
  (clustering, advanced monitoring) are not required for the prototype.

---

## ADR-008: PolitiFact corpus as validation baseline

**Status:** Accepted
**Date:** 2026-04

### Context

A multi-agent system producing fact-checking verdicts must be validated
against known ground truth. Without a baseline, there is no way to
distinguish a working system from a confidently wrong one. The validation
strategy must use a corpus of claims with independently established
verdicts, be reproducible, and cover a range of claim types and
complexity levels.

PolitiFact publishes its full ruling history with claim text, verdict
(True / Mostly True / Half True / Mostly False / False / Pants on Fire),
source, and date. The corpus is publicly accessible, well-maintained,
and covers thousands of claims across domains including healthcare,
economics, and policy — all relevant to the system's intended use cases.

Google's Fact Check Tools API indexes ClaimReview markup from hundreds
of fact-checking organizations including PolitiFact, Snopes, and
FactCheck.org. This API is the system's primary fact-check retrieval
mechanism and its output can be compared directly against PolitiFact's
published verdicts.

### Decision

The validation corpus is a curated set of 50 PolitiFact claims selected
to cover:
- 10 claims with `True` or `Mostly True` verdicts
- 10 claims with `False` or `Pants on Fire` verdicts
- 10 claims with `Half True` verdicts (the hard middle)
- 10 claims indexed in Google Fact Check Tools API (ClaimReview present)
- 10 claims not yet indexed in ClaimReview (system must reason from
  coverage analysis and primary sources alone)

The last category is the most important for demonstrating swarm value:
these are the claims a single agent calling ClaimReview would fail on,
and where parallel coverage analysis and domain evidence agents provide
signal unavailable to a monolithic approach.

### Consequences

- The validation corpus must be assembled and committed before any
  agent evaluation begins. Selecting claims after seeing results
  introduces selection bias.
- Verdict mapping from HL7v2 OBX confidence scores to PolitiFact's
  six-tier scale requires a defined mapping convention. This is
  documented in `hl7-segment-spec.md`.
- The 50-claim corpus is intentionally small enough to inspect manually,
  which is a feature: failures should be explainable by reading the
  OBX log, not hidden in aggregate statistics.

---

## ADR-009: Orchestrator-as-hub over peer-to-peer MCP topology

**Status:** Accepted
**Date:** 2026-04

### Context

MCP (Model Context Protocol) is used as the control plane between the
orchestrator and subagents. A design choice exists between a hub-and-spoke
topology (all MCP communication flows through the orchestrator) and a
peer-to-peer topology (subagents communicate directly with one another
via MCP).

Peer-to-peer MCP would allow subagents to request data from one another
directly, potentially reducing latency and orchestrator load. However,
it introduces implicit coupling: each subagent must know the capabilities,
addresses, and availability of other subagents. Adding or replacing an
agent requires updating all agents that communicate with it. Failure modes
become harder to trace.

Hub-and-spoke keeps subagents isolated. Each subagent exposes an MCP
server with its own tool surface. The orchestrator holds all MCP client
connections. Subagents do not know other subagents exist.

### Decision

Hub-and-spoke. The orchestrator is the sole MCP client. Subagents are
MCP servers only. No subagent-to-subagent MCP connections are permitted.

Two interaction patterns are supported:

**Pull pattern** — subagent tells orchestrator how to retrieve data:
```
Orchestrator → MCP → Subagent: invoke tool
Subagent → MCP → Orchestrator: "fetch ^CLAIM(id,'entities') from YottaDB"
Orchestrator fetches, returns data to subagent via MCP
Subagent reasons, writes OBX rows, sends HL7 via Mirth
```

**Push pattern** — orchestrator tells subagent where to send output:
```
Orchestrator → MCP → Subagent: "analyze X, send findings to channel Y"
Subagent reasons, writes OBX rows, Mirth routes to channel Y
Orchestrator monitors channel Y for ACK
```

The orchestrator selects the appropriate pattern per agent based on
whether the agent's work depends on data from prior agents (pull) or
produces data for downstream agents (push).

### Consequences

- The orchestrator is the single point of failure for the MCP control
  plane. If the orchestrator process fails, in-flight MCP calls are
  lost. Mirth-delivered HL7v2 messages already written to YottaDB
  are not affected — the two planes fail independently.
- Subagents are stateless with respect to other agents. An agent
  can be restarted, replaced, or scaled without notifying other agents.
- The orchestrator must maintain the DAG of agent dependencies and
  the mapping of which agent owns which OBX observation codes. This
  is configuration, not runtime state.
- Subagent MCP tool surfaces must be designed to accept all required
  context as tool call parameters. Subagents cannot rely on shared
  memory or inter-agent communication for context.

---

## ADR-010: Stateless orchestrator reads agent state via MCP tool calls

**Status:** Accepted
**Date:** 2026-04

### Context

The orchestrator coordinates agent execution and must be able to inspect
the current reasoning state of any agent at any point. Two options exist:
the orchestrator maintains its own copy of agent state (stateful
orchestrator), or the orchestrator reads agent state on demand via MCP
tool calls to the relevant agent's YottaDB instance (stateless orchestrator).

A stateful orchestrator duplicates data, creates synchronization
requirements, and introduces a second source of truth. If orchestrator
state diverges from agent YottaDB state, the system is in an inconsistent
condition that is difficult to detect and recover from.

A stateless orchestrator treats each agent's YottaDB as the authoritative
store for that agent's reasoning state. The orchestrator reads state
when it needs it, via MCP tool calls, and does not cache it. This
eliminates the synchronization problem entirely.

### Decision

The orchestrator is stateless with respect to agent reasoning state.
It maintains only:
- The DAG of agent execution order and dependencies
- The set of active MCP client connections
- The current run ID and claim under investigation
- A completion register: which agents have emitted terminal OBX status
  (`F` or `X`) for their assigned codes in the current run

All other state — OBX rows, intermediate findings, confidence scores —
lives in the agent's YottaDB instance and is read via MCP tool calls
when the orchestrator needs it. The orchestrator never writes to agent
YottaDB instances directly.

The completion register is ephemeral. If the orchestrator restarts
during a run, it can reconstruct completion state by issuing MCP
tool calls to each agent to query their current OBX terminal status
rows.

### Consequences

- MCP tool calls for state reads add latency compared to local memory
  reads. This is acceptable because orchestrator state reads are
  infrequent (completion checks, pre-synthesis review) rather than
  per-token.
- Each agent bundle must expose a YottaDB query tool via its MCP
  server. The minimum required tools are:
  - `get_observations(claim_id, code?)` — returns OBX rows, optionally
    filtered by code
  - `get_terminal_status(claim_id)` — returns whether any `F` or `X`
    rows exist for this run
- The orchestrator's restart recovery procedure must be documented
  and tested. Reconstructing completion state from agent MCP calls
  is deterministic but requires all agent containers to be reachable.
- Agent YottaDB instances are the system's ground truth. Backup and
  persistence policy for YottaDB volumes is a production concern
  outside the prototype scope.
