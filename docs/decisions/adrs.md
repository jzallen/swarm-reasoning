# Architecture Decision Records — swarm-reasoning

Architecture Decision Records (ADRs) document significant design choices,
the context that drove them, the options considered, and the rationale for
the decision made. They are written at decision time and never retroactively
revised — superseded ADRs are marked as such and linked to their replacement.

---

## ADR-001: HL7v2 as inter-agent wire format over JSON

**Status:** Superseded by ADR-011
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
for this system.

### Supersession Note

ADR-011 replaces this decision. The epistemic status model, append-only
semantics, and observation structure that motivated the HL7v2 choice are
preserved in a typed JSON observation schema. The HL7v2 encoding added
complexity without functional benefit over a well-typed JSON format with
explicit status fields. The cross-domain insight (healthcare protocols
solving epistemic state tracking) informed the design of the replacement
schema but does not require the healthcare encoding.

---

## ADR-002: YottaDB over relational or document databases for agent state

**Status:** Superseded by ADR-012
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

### Decision

Option C (YottaDB). The absence of a serialization gap between HL7v2 wire
format and YottaDB storage was the decisive factor.

### Supersession Note

ADR-012 replaces this decision. The zero-serialization-gap argument was
circular — YottaDB was chosen because it maps to HL7v2, and HL7v2 was
chosen because it maps to YottaDB. With HL7v2 superseded by JSON
observations (ADR-011), YottaDB's primary advantage evaporates. Redis
Streams provides append-only log semantics, consumer groups, and streaming
delivery with dramatically lower operational overhead (1 container vs. 11).

---

## ADR-003: Append-only observation log over mutable shared state

**Status:** Accepted (updated)
**Date:** 2026-04
**Updated:** 2026-04

### Context

As agents contribute findings to a fact-checking run, the collective
reasoning state grows. A design choice exists between mutable shared state
(agents overwrite or update a central record) and an append-only log
(agents add new observation entries; earlier entries are never modified).

Mutable shared state simplifies the final read — there is always one
current value per field. However, it destroys the history of how the
system's confidence evolved, makes concurrent writes conflict-prone,
and prevents attribution of which agent asserted what at which point.

An append-only log preserves the full reasoning trajectory. Corrections
are expressed as new observation entries with `C` (corrected) status
referencing the original observation, not as overwrites. The synthesizer
reads the full log and resolves the current authoritative value by status
and sequence.

### Decision

Append-only log. The reasoning log is the primary source of the system's
interpretability claim. The audit trail — which agent introduced a finding,
which agent corrected it, how confidence evolved from `P` to `F` — is
only possible if history is preserved.

### Update Note

This decision survives the transport change from HL7v2/YottaDB to JSON/Redis
Streams. Redis Streams are append-only by nature — entries are immutable
once written. The `XADD` command appends; there is no update-in-place.
The log resolution logic in the synthesizer is unchanged: given multiple
observations for the same code, select the most recent `F` or `C` status
entry as authoritative.

### Consequences

- The synthesizer must implement log resolution logic: given multiple
  observation entries for the same code, determine the authoritative
  current value by selecting the most recent `F` or `C` status entry.
- Redis Stream storage grows monotonically per run. `MAXLEN` or `MINID`
  trimming policy is required for long-running deployments but is out
  of scope for the prototype.
- Query patterns must account for log structure. "What is the current
  confidence score?" requires a scan of all CONFIDENCE_SCORE entries
  and selection of the latest authoritative one.

---

## ADR-004: Tool-based observation construction over LLM-generated strings

**Status:** Accepted (updated)
**Date:** 2026-04
**Updated:** 2026-04

### Context

Agents must produce valid observation entries as part of their output.
Two approaches exist: the LLM generates raw observation JSON directly, or
the LLM calls structured tools that produce valid entries internally.

LLM generation of structured formats is a known failure mode. Even with
JSON, deeply nested schemas with specific field conventions and coded values
are error-prone. A single malformed observation can corrupt downstream
processing.

Tool-based construction moves structural responsibility to deterministic
code. The LLM decides *what* to assert; the tool decides *how* to
serialize it. Structural errors become impossible. Semantic errors (wrong
interpretation) remain, but they are recoverable and auditable.

### Decision

Tool-based construction. The LLM calls structured tools that produce
valid observation entries. The tool surface is small and stable:

```typescript
startStream(runId, agent, phase)
publishObservation({ code, value, valueType, units, range, status })
stopStream(runId, agent, finalStatus)
```

Structural correctness is guaranteed by the tool layer. The LLM's role
is limited to deciding which tools to call and with what values — which
is exactly what LLMs are reliable at.

### Update Note

This decision survives the transport change. The tool layer now produces
typed JSON observation objects and publishes them to Redis Streams instead
of constructing HL7v2 OBX segments and writing to YottaDB. The tool
surface is simplified — no escape sequence handling, no positional field
encoding. Validation of observation codes against the registry remains
at the tool layer.

### Consequences

- Every new observation code must be registered in `obx-code-registry.json`
  before agents can use it. The tool validates codes against the registry
  at write time and rejects unknown codes.
- The tool layer enforces observation code ownership — only the agent
  registered as the owner of a given code can write it.

---

## ADR-005: Observation result status as epistemic state carrier

**Status:** Accepted
**Date:** 2026-04

### Context

In a multi-agent pipeline where findings evolve over time, downstream
agents need to know whether an upstream observation is a hypothesis,
a confirmed finding, a correction of an earlier finding, or a
retraction. This epistemic state must be structural — carried in the
data, not inferred from prose — so that agents can act on it
programmatically.

### Decision

Observation entries carry a `status` field with the following values:

| Status | Meaning in this system |
|---|---|
| `P` | Preliminary — hypothesis or initial finding, not yet corroborated |
| `F` | Final — confirmed finding, agent considers this settled |
| `C` | Corrected — supersedes an earlier observation of the same code |
| `X` | Cancelled — claim determined not check-worthy or finding retracted |

This model was informed by HL7v2's OBX.11 result status semantics, which
solved the same epistemic state tracking problem in clinical observation
reporting. The status values are carried as a typed field in the JSON
observation schema rather than in a positional HL7v2 field.

The synthesizer treats only `F` and `C` status entries as authoritative
inputs to the final verdict. `P` entries are informational. `X` entries
are excluded from synthesis but retained in the log for auditability.

### Consequences

- Agents must set status deliberately. Emitting `F` status is a
  commitment that the finding is settled from that agent's perspective.
- The orchestrator uses status as a completion signal: when all expected
  agents have emitted at least one `F` or `X` entry for their assigned
  observation codes, the run is eligible for synthesis.
- `P` status entries from parallel agents may temporarily contradict one
  another. This is expected and resolved by the synthesizer.

---

## ADR-006: Edge serialization to JSON via Mirth adapter

**Status:** Superseded by ADR-011
**Date:** 2026-04

### Context

Downstream consumers — dashboards, REST API clients, analyst tools —
expect JSON. They should not need to understand HL7v2 segment structure.
A serialization adapter was required to transform finalized HL7v2 messages
into JSON at the system boundary.

### Decision

Mirth Connect serves as the edge serialization adapter. A dedicated
Mirth channel subscribes to finalized messages and maps OBX rows to JSON.

### Supersession Note

ADR-011 replaces this decision. With JSON as the native observation format
(ADR-011), no edge serialization adapter is needed. The observation schema
is directly consumable by dashboards, API clients, and analyst tools.
The edge-serializer agent role is eliminated.

---

## ADR-007: Mirth Connect as HL7v2 transport layer

**Status:** Superseded by ADR-012
**Date:** 2026-04

### Context

HL7v2 messages must be routed between agent bundles. A transport layer
is needed that understands HL7v2 framing, handles ACK/NACK semantics,
and can deliver messages reliably between containers.

### Decision

Each agent bundle includes a Mirth Connect instance. The orchestrator's
Mirth instance is the routing hub.

### Supersession Note

ADR-012 replaces this decision. With HL7v2 superseded by JSON observations
(ADR-011), Mirth Connect's MLLP framing and HL7v2-native features have
no role. Redis Streams replaces Mirth as the transport layer, reducing
the container count from 10 Mirth instances to 1 Redis instance. Delivery
guarantees are provided by Redis Streams consumer groups and
acknowledgment, replacing Mirth's MLLP ACK/NACK.

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
  agent evaluation begins.
- Verdict mapping from confidence scores to PolitiFact's six-tier scale
  requires a defined mapping convention. This is documented in the
  observation schema spec.
- The 50-claim corpus is intentionally small enough to inspect manually.

---

## ADR-009: Orchestrator-as-hub over peer-to-peer MCP topology

**Status:** Accepted (updated)
**Date:** 2026-04
**Updated:** 2026-04

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
agent requires updating all agents that communicate with it.

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
Subagent → MCP → Orchestrator: "read observations from stream X"
Orchestrator reads from Redis Stream, returns data to subagent via MCP
Subagent reasons, publishes observations to its own stream
```

**Push pattern** — orchestrator tells subagent where to send output:
```
Orchestrator → MCP → Subagent: "analyze X, publish findings to your stream"
Subagent reasons, publishes observations to its Redis Stream
Orchestrator monitors stream for STOP message
```

### Update Note

The interaction patterns are unchanged. The data plane transport changed
from Mirth/HL7v2 to Redis Streams/JSON, but the MCP control plane remains
hub-and-spoke. The two planes (MCP control + Redis Streams data) continue
to fail independently.

### Consequences

- The orchestrator is the single point of failure for the MCP control
  plane. If the orchestrator process fails, in-flight MCP calls are
  lost. Observations already written to Redis Streams are not affected.
- Subagents are stateless with respect to other agents. An agent can
  be restarted, replaced, or scaled without notifying other agents.
- The orchestrator maintains the DAG of agent dependencies and the
  mapping of which agent owns which observation codes.

---

## ADR-010: Stateless orchestrator reads agent state on demand

**Status:** Accepted (updated)
**Date:** 2026-04
**Updated:** 2026-04

### Context

The orchestrator coordinates agent execution and must be able to inspect
the current reasoning state of any agent at any point. Two options exist:
the orchestrator maintains its own copy of agent state (stateful
orchestrator), or the orchestrator reads agent state on demand from the
authoritative store (stateless orchestrator).

A stateful orchestrator duplicates data, creates synchronization
requirements, and introduces a second source of truth.

### Decision

The orchestrator is stateless with respect to agent reasoning state.
It maintains only:
- The DAG of agent execution order and dependencies
- The set of active MCP client connections
- The current run ID and claim under investigation
- A completion register: which agents have emitted terminal status
  (`F` or `X`) for their assigned codes in the current run

All other state — observations, intermediate findings, confidence
scores — lives in Redis Streams and is read via `XRANGE` queries
when the orchestrator needs it. The orchestrator never writes to
agent streams directly.

The completion register is ephemeral. If the orchestrator restarts
during a run, it can reconstruct completion state by scanning each
agent's stream for STOP messages.

### Update Note

The stateless orchestrator pattern maps cleanly to Redis Streams. Instead
of issuing MCP tool calls to each agent's YottaDB instance to query
state, the orchestrator reads directly from Redis Streams using `XRANGE`.
This eliminates the MCP roundtrip for state reads — the orchestrator
subscribes to agent streams and receives observations in real time via
`XREADGROUP`. MCP remains the control plane for issuing commands to
agents; Redis Streams is the data plane for reading results.

### Consequences

- Each agent publishes observations to its own Redis Stream
  (`reasoning:{runId}:{agent}`). The orchestrator consumes from all
  active agent streams for a given run.
- The minimum agent contract is: publish START, publish one or more
  observations, publish STOP with terminal status. The orchestrator
  can verify completion by checking for STOP messages.
- Agent Redis Streams are the system's ground truth. Redis persistence
  configuration (RDB snapshots or AOF) determines durability guarantees.

---

## ADR-011: JSON observation schema as inter-agent wire format

**Status:** Accepted
**Date:** 2026-04
**Supersedes:** ADR-001, ADR-006

### Context

ADR-001 chose HL7v2 pipe-delimited messaging as the inter-agent wire
format. The rationale centered on three properties: line-level validity
for streaming, native epistemic status (OBX.11 result status), and
zero-serialization alignment with YottaDB storage.

Re-evaluation revealed that these properties are not unique to HL7v2:

1. **Epistemic status** — The P/F/C/X model is a four-value enum. A
   `status` field in a JSON object carries identical semantics.
2. **Streaming** — Redis Streams delivers discrete messages. Each
   message is independently valid regardless of format. The streaming
   argument applies to the transport layer, not the encoding.
3. **YottaDB alignment** — With YottaDB superseded (ADR-012), the
   zero-serialization-gap argument is circular and no longer applies.
4. **Edge serialization** — HL7v2 required a dedicated serialization
   adapter (ADR-006) to produce JSON for external consumers. A native
   JSON format eliminates this translation layer entirely.

The HL7v2 encoding added domain-specific complexity (escape sequences,
positional field semantics, MLLP framing) without functional benefit
over a well-typed JSON schema. The cross-domain insight — that healthcare
protocols solved epistemic state tracking, append-only audit, and
provenance decades ago — informed the design of the replacement schema.
The insight is preserved; the encoding is not.

### Decision

Observations are encoded as typed JSON objects conforming to the
following schema:

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

The observation code registry (`obx-code-registry.json`) remains the
governing contract for valid codes, value types, ownership, and
reference ranges. The tool layer validates against it at write time.

### Consequences

- The edge-serializer agent is eliminated. The consumer API reads
  JSON observations directly from Redis Streams.
- No escape sequence handling is needed. JSON string escaping is
  handled by standard libraries.
- The `obx-code-registry.json` file is unchanged. The `FCK` coding
  system identifier is retained in the registry but is not encoded
  into observation values (unlike the HL7v2 `{code}^^FCK` pattern).
- CWE-typed values use a structured format: `{code}^{display}^{system}`
  stored as a string, consistent with the registry. Alternatively,
  implementations may parse this into a structured object.
- Verdict mapping to PolitiFact scale is unchanged (see observation
  schema spec, Section 9).

---

## ADR-012: Redis Streams as observation transport with Kafka graduation path

**Status:** Accepted
**Date:** 2026-04
**Supersedes:** ADR-002, ADR-007

### Context

ADR-002 chose YottaDB as per-agent state storage (11 instances). ADR-007
chose Mirth Connect as HL7v2 transport (10 instances). Together they
accounted for 21 of the system's 33 containers, all in service of a
wire format that has been superseded (ADR-011).

The system needs a transport and storage layer that provides:
- Append-only log semantics (ADR-003)
- Streaming delivery with consumer group support
- Per-agent, per-run stream isolation
- Query capability for the synthesizer to read full reasoning logs
- Low operational overhead for local development

### Options Considered

**Option A — Kafka**
Industry-standard event streaming. Durable, replayable, partitioned.
Consumer groups, exactly-once semantics, schema registry integration.
Operationally heavier than needed for a prototype (JVM, memory
requirements), but KRaft mode reduces to 1 container.

**Option B — Redis Streams (chosen for development)**
Append-only log with consumer groups (`XREADGROUP`), blocking reads
(`XREAD BLOCK`), range queries (`XRANGE`), and automatic entry ID
sequencing. Single container. Low memory overhead. Native support in
all target languages (Python, TypeScript). `MAXLEN` for retention
control.

**Option C — PostgreSQL with LISTEN/NOTIFY**
Relational storage with notification channel. Append-only via
INSERT-only policy. No native streaming consumer groups. NOTIFY
payload limit (8000 bytes) may constrain large observations.

### Decision

Redis Streams for development and prototyping. The transport layer is
accessed through an abstract `ReasoningStream` interface that decouples
agents from the specific backend:

```typescript
interface ReasoningStream {
  startStream(runId: string, agent: string, phase: string): Promise<void>;
  publish(observation: Observation): Promise<string>;
  stopStream(runId: string, agent: string, finalStatus: 'F' | 'X'): Promise<void>;

  subscribe(runId: string, agents: string[],
            handler: (msg: StreamMessage) => void): Promise<Subscription>;

  getObservations(runId: string, opts?: {
    agent?: string; code?: string; status?: EpistemicStatus;
  }): Promise<Observation[]>;

  isComplete(runId: string, expectedAgents: string[]): Promise<boolean>;
}
```

A factory function selects the backend based on configuration:

```typescript
function createReasoningStream(config: StreamConfig): ReasoningStream {
  if (config.backend === 'redis') return new RedisReasoningStream(config.redis);
  if (config.backend === 'kafka') return new KafkaReasoningStream(config.kafka);
}
```

### Redis Stream Key Design

```
reasoning:{runId}:{agent}     — per-agent observation stream
reasoning:{runId}:_control    — orchestrator commands (optional)
```

Consumer group: `orchestrator` — the sole consumer of all agent streams,
consistent with the hub-and-spoke topology (ADR-009).

### Graduation Path

Redis Streams serves as the development and prototype backend. Kafka
is the production graduation target. The `ReasoningStream` interface
makes this a configuration change, not a code change. Key mapping:

| Concern | Redis Streams (dev) | Kafka (prod) |
|---|---|---|
| Stream identity | Key: `reasoning:{runId}:{agent}` | Topic: `agent.{name}`, key: `runId` |
| Subscribe | `XREADGROUP BLOCK` | `KafkaConsumer.subscribe()` |
| Query log | `XRANGE` | Topic replay from offset 0 |
| Retention | `MAXLEN` / `MINID` | Log compaction + retention policy |
| Delivery guarantee | At-least-once (consumer ACK) | Exactly-once (with transactions) |

### Consequences

- Container count drops from 33 to approximately 13: 1 Redis, 10 agents,
  1 orchestrator, 1 consumer API.
- All agents share a single Redis instance. Stream isolation is by key,
  not by database instance. This is simpler to operate but means a Redis
  failure affects all agents simultaneously.
- Redis persistence must be configured for durability. `appendonly yes`
  (AOF) provides crash recovery. For the prototype, RDB snapshots at
  default intervals are sufficient.
- The `ReasoningStream` interface is the only component that knows
  about Redis or Kafka. Agents, the orchestrator, and the synthesizer
  depend on the interface, not the implementation.

---

## ADR-013: Two communication planes — MCP control + Redis Streams data

**Status:** Accepted
**Date:** 2026-04

### Context

The system uses two distinct communication mechanisms: MCP for control
(orchestrator issuing commands to agents) and Redis Streams for data
(agents publishing observations). This separation was present in the
original architecture (MCP + Mirth/HL7v2) and is preserved in the
new stack.

### Decision

The two-plane architecture is retained:

**Control plane — MCP (Model Context Protocol)**
- Orchestrator → Agent: task assignment, configuration, queries
- Agent → Orchestrator: tool call results, status responses
- Synchronous request/response pattern
- Hub-and-spoke topology (ADR-009)

**Data plane — Redis Streams**
- Agent → Stream: observation publication (START, OBS, STOP)
- Orchestrator ← Stream: observation consumption via consumer groups
- Asynchronous append/subscribe pattern
- Agents write to their own stream; orchestrator reads all streams

The planes fail independently. If MCP is down, the orchestrator cannot
issue new commands, but agents can continue publishing observations to
Redis Streams. If Redis is down, agents cannot publish observations,
but MCP commands still function. The orchestrator can detect plane
failures independently and report degraded status.

### Consequences

- Agents must be resilient to Redis unavailability: buffer observations
  locally and retry publication when Redis recovers.
- The orchestrator monitors both planes. Health checks cover MCP
  connectivity (per-agent) and Redis connectivity (single instance).
- Observation delivery is not confirmed via MCP. The orchestrator
  detects completion by reading STOP messages from Redis Streams,
  not by receiving MCP responses.
