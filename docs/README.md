# swarm-reasoning — Architecture & Design Documentation

**Version:** 0.2.0
**Project:** Multi-agent fact-checking system using structured JSON observations
streamed via Redis Streams as inter-agent communication. Ten coordinating
agents produce confidence-scored verdicts against a PolitiFact validation
corpus through three-phase swarm reasoning.
**Stack:** Python / LangChain · Redis Streams · FastAPI · TypeScript / Node 20 ·
MCP (Model Context Protocol) · Docker Compose

---

## Document Index

### decisions/
Architecture Decision Records in [MADR v3.0](https://adr.github.io/madr/) format — one file per decision, YAML frontmatter for machine parsing.

| File | Status |
|---|---|
| `index.md` | Index table linking all 13 ADRs |
| `template.md` | MADR v3.0 template for new ADRs |
| `0001-hl7v2-wire-format.md` | Superseded by ADR-0011 |
| `0002-yottadb-agent-state.md` | Superseded by ADR-0012 |
| `0003-append-only-observation-log.md` | Accepted |
| `0004-tool-based-observation-construction.md` | Accepted |
| `0005-epistemic-status-carrier.md` | Accepted |
| `0006-edge-serialization-mirth.md` | Superseded by ADR-0011 |
| `0007-mirth-connect-transport.md` | Superseded by ADR-0012 |
| `0008-politifact-validation-corpus.md` | Accepted |
| `0009-hub-and-spoke-mcp-topology.md` | Accepted |
| `0010-stateless-orchestrator.md` | Accepted |
| `0011-json-observation-schema.md` | Accepted |
| `0012-redis-streams-transport.md` | Accepted |
| `0013-two-communication-planes.md` | Accepted |

---

### domain/
Domain model — entities, contracts, and business rules.

| File | Format | Contents |
|---|---|---|
| `observation-schema-spec.md` | Markdown | JSON observation schema — stream message types (START/OBS/STOP), observation fields, value types, epistemic status semantics, correction pattern, Redis Stream key design, delivery acknowledgment, verdict mapping |
| `obx-code-registry.json` | JSON | 31 canonical observation codes across all 10 agents — code, display, owner agent, value type, units, reference range, description |
| `claim-lifecycle.dmn` | DMN 1.3 XML | Two decision tables: `DetermineClaimTransition` (run status progression) and `DetermineOBXResolution` (authoritative observation selection for synthesis) |
| `erd-full.mermaid` | Mermaid ERD | Data model — RUN, CLAIM, STREAM_ENTRY, OBSERVATION, OBS_CODE, AGENT, CONSUMER_GROUP entities with Redis Stream key design |

> Render `erd-full.mermaid` at [mermaid.live](https://mermaid.live)
> Load `claim-lifecycle.dmn` in [Camunda Modeler](https://camunda.com/download/modeler/) or [demo.bpmn.io](https://demo.bpmn.io)

---

### api/
API specification.

| File | Format | Contents |
|---|---|---|
| `openapi.yaml` | OpenAPI 3.1 | 11 REST endpoint paths across Claims, Runs, Verdicts, Audit, and System tags |

> Paste into [editor.swagger.io](https://editor.swagger.io) for interactive docs.

---

### architecture/
System-level views.

| File | Format | Contents |
|---|---|---|
| `c4-containers.mermaid` | Mermaid C4Container | All 10 agents, orchestrator, consumer API, Redis, external APIs, and inter-service relationships |
| `agent-topology.mermaid` | Mermaid flowchart | Three-phase execution topology — sequential ingestion, parallel fan-out, sequential synthesis — with MCP and Redis Streams planes distinguished |
| `mcp-topology.mermaid` | Mermaid flowchart | Hub-and-spoke MCP control plane — orchestrator as sole client, all subagents as servers, pull and push interaction patterns, forbidden subagent-to-subagent connections |
| `dfd-trust-boundaries.mermaid` | Mermaid flowchart | Data flow diagram with external, DMZ, trusted, and LLM trust zones — PII and external API trust annotations |
| `observation-stream-lifecycle.md` | Markdown | End-to-end prose description of how observation streams are opened, grown, consumed, and finalized — including the two-plane principle (MCP control + Redis Streams data) |

---

### diagrams/sequence/
Behavioural sequence diagrams — runtime flows over time.

| File | Format | Contents |
|---|---|---|
| `seq-orchestrator-pull.mermaid` | Mermaid sequence | Pull pattern — blindspot detector requests COVERAGE_* data; orchestrator reads from coverage agent streams via XRANGE and returns consolidated observations |
| `seq-orchestrator-push.mermaid` | Mermaid sequence | Push pattern — orchestrator dispatches coverage-left; agent reasons independently and publishes observations to its Redis Stream |
| `seq-claim-ingestion.mermaid` | Mermaid sequence | Phase 1 — claim submission through ingestion, detection, entity extraction, and check-worthiness gate |
| `seq-agent-fanout.mermaid` | Mermaid sequence | Phase 2 — parallel dispatch and independent execution of claimreview-matcher, three coverage agents, and domain-evidence |
| `seq-synthesis.mermaid` | Mermaid sequence | Phase 3 — blindspot detection (pull pattern) followed by synthesis, observation resolution, confidence scoring, and verdict emission |
| `seq-edge-serialization.mermaid` | Mermaid sequence | Publication — consumer API reads finalized observations from Redis Streams, applies resolution, validates schema, and serves verdict |

---

### diagrams/state/
State machine diagrams.

| File | Format | Contents |
|---|---|---|
| `state-claim.mermaid` | Mermaid stateDiagram-v2 | Run lifecycle — INGESTED → ANALYZING → SYNTHESIZED → PUBLISHED (and CANCELLED) with guard conditions |
| `state-obx-result.mermaid` | Mermaid stateDiagram-v2 | Observation result status transitions — P → F, P → X, F → C, C → C — with synthesizer behaviour per terminal state |

---

### features/
Gherkin feature files — executable acceptance test specifications.

| File | Scenarios | Coverage |
|---|---|---|
| `claim-ingestion.feature` | 13 | Submission validation, ingestion observation writes, check-worthiness gate, entity extraction, Phase 2 trigger |
| `agent-coordination.feature` | 14 | Hub-and-spoke topology, push pattern, pull pattern, observation ordering, delivery retry semantics, completion register, orchestrator restart recovery |
| `verdict-synthesis.feature` | 13 | Observation resolution, confidence computation, verdict mapping, ClaimReview override, synthesizer output, run state transition |
| `validation-baseline.feature` | 9 | Per-corpus-category accuracy, swarm vs single-agent baseline, audit log coverage, run latency budget |
| `verdict-publication.feature` | 12 | Trigger conditions, observation resolution, required JSON fields, schema validation, error path, Consumer API delivery |

> Compatible with `@cucumber/cucumber` and `jest-cucumber`.

---

### requirements/nfrs/
Non-functional requirements — one file per NFR, Planguage + SEI Quality Attribute Scenario format, YAML frontmatter for machine parsing.

| File | Contents |
|---|---|
| `index.md` | Index table grouped by ISO/IEC 25010 category |
| `template.md` | NFR template (Planguage + SEI QAS) |
| `NFR-001-*` through `NFR-004-*` | Performance (4 NFRs) |
| `NFR-005-*` through `NFR-009-*` | Reliability (5 NFRs) |
| `NFR-010-*` through `NFR-013-*` | Security (4 NFRs) |
| `NFR-014-*` through `NFR-016-*` | Maintainability (3 NFRs) |
| `NFR-017-*` through `NFR-018-*` | Portability (2 NFRs) |
| `NFR-019-*` through `NFR-021-*` | Correctness (3 NFRs) |
| `NFR-022-*` through `NFR-023-*` | Auditability (2 NFRs) |
| `NFR-024-*` through `NFR-027-*` | Observability (4 NFRs) |

---

### infrastructure/
Local development configuration.

| File | Format | Contents |
|---|---|---|
| `docker-compose.yml` | Docker Compose | Full local stack — 13 containers: 10 agent processes, 1 Redis instance, orchestrator, consumer-api |
| `docker-topology.mermaid` | Mermaid flowchart | Container dependency graph, port bindings (host-exposed vs internal-only), MCP connections (control plane), Redis Streams (data plane), startup order |

> **Entry point:** `docker compose -f docs/infrastructure/docker-compose.yml up`
> Consumer API available at `http://localhost:8000`
> Redis available at `redis://localhost:6379` (dev only)
> Required environment variables: `ANTHROPIC_API_KEY`, `GOOGLE_FACTCHECK_API_KEY`, `NEWSAPI_KEY`

---

## Rendering Guide

| Extension | Tool |
|---|---|
| `.mermaid` | [mermaid.live](https://mermaid.live) — paste and render |
| `.yaml` (OpenAPI) | [editor.swagger.io](https://editor.swagger.io) |
| `.dmn` | [demo.bpmn.io](https://demo.bpmn.io) or Camunda Modeler |
| `.feature` | Any Gherkin-compatible editor (VS Code + Cucumber extension) |

---

## Key Architectural Decisions at a Glance

| Decision | Choice | ADR |
|---|---|---|
| Inter-agent wire format | JSON observation schema | [ADR-0011](decisions/0011-json-observation-schema.md) |
| Observation transport & storage | Redis Streams (dev), Kafka graduation path (prod) | [ADR-0012](decisions/0012-redis-streams-transport.md) |
| Log structure | Append-only observations, never overwritten | [ADR-0003](decisions/0003-append-only-observation-log.md) |
| Observation construction | Tool-based — LLMs never generate raw observations | [ADR-0004](decisions/0004-tool-based-observation-construction.md) |
| Epistemic state carrier | Observation `status` field (P/F/C/X) | [ADR-0005](decisions/0005-epistemic-status-carrier.md) |
| Edge serialization | Eliminated — observations are natively JSON | [ADR-0011](decisions/0011-json-observation-schema.md) |
| Validation baseline | 50-claim PolitiFact corpus, 10 non-indexed claims | [ADR-0008](decisions/0008-politifact-validation-corpus.md) |
| MCP topology | Orchestrator-as-hub, no subagent-to-subagent | [ADR-0009](decisions/0009-hub-and-spoke-mcp-topology.md) |
| Orchestrator state | Stateless — reads agent streams via XRANGE on demand | [ADR-0010](decisions/0010-stateless-orchestrator.md) |
| Communication planes | MCP control + Redis Streams data, fail independently | [ADR-0013](decisions/0013-two-communication-planes.md) |

---

## Two Communication Planes

The system uses two distinct communication planes that fail independently:

| Plane | Protocol | Purpose | Failure consequence |
|---|---|---|---|
| MCP control | MCP over TCP | Orchestrator dispatches tasks, reads state, receives data requests from agents | In-flight task lost; recoverable via orchestrator restart |
| Redis Streams data | Redis protocol | Agents publish observations; orchestrator consumes via XREADGROUP | Observations already written are safe; unacknowledged messages reclaimable via XPENDING |

---

## Validation Strategy

The system's output is validated against a curated 50-claim PolitiFact
corpus. The corpus is divided into five categories of 10 claims each:

| Category | Description | Key metric |
|---|---|---|
| TRUE_MOSTLY_TRUE | Known true claims | >= 7/10 correct alignment |
| FALSE_PANTS_FIRE | Known false claims | >= 7/10 correct alignment |
| HALF_TRUE | Ambiguous claims | >= 5/10 in adjacent tiers |
| CLAIMREVIEW_INDEXED | Claims in Google Fact Check Tools | >= 8/10 match ClaimReview verdict |
| NOT_CLAIMREVIEW_INDEXED | Claims not yet in ClaimReview | Swarm beats single-agent by >= 20pp |

The fifth category — claims not yet indexed in ClaimReview — is the
primary proof-of-value test. A single agent calling ClaimReview returns
no match for these claims. The swarm's parallel coverage analysis and
domain evidence agents provide signal unavailable to a monolithic approach.

---

## The Audit Trail

Every published verdict is backed by the complete observation stream
retained in Redis Streams. This includes every observation written by
every agent during the run, in sequence order, with full attribution
via the `agent` field. The JSON verdict delivered to consumers is a
projection of this stream and is disposable. The observation log is
authoritative.

This interpretability is architecturally guaranteed by the append-only
stream design — not bolted on after the fact.
