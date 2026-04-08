# hl7-agent-factchecker — Architecture & Design Documentation

**Version:** 0.1.0
**Project:** Multi-agent fact-checking system using HL7v2 as inter-agent
wire format, YottaDB as MUMPS-native storage, and Mirth Connect as
HL7v2 transport layer. Ten coordinating agents produce confidence-scored
verdicts against a PolitiFact validation corpus.
**Stack:** Python / LangChain · YottaDB · Mirth Connect · FastAPI ·
MCP (Model Context Protocol) · Docker Compose

---

## Document Index

### decisions/
Architecture Decision Records — why key choices were made.

| File | Contents |
|---|---|
| `adrs.md` | ADR-001 through ADR-010 covering HL7v2 wire format, YottaDB storage, append-only OBX log, tool-based construction, epistemic status semantics, edge serialization, Mirth transport, PolitiFact validation baseline, hub-and-spoke MCP topology, and stateless orchestrator |

---

### domain/
Domain model — entities, contracts, and business rules.

| File | Format | Contents |
|---|---|---|
| `hl7-segment-spec.md` | Markdown | HL7v2 implementation guide — MSH, PID, OBX, NTE field usage, value types, result status semantics, escape sequences, ACK conventions, and PolitiFact verdict mapping |
| `obx-code-registry.json` | JSON | 31 canonical OBX observation codes across all 10 agents — code, display, owner agent, value type, units, reference range, description |
| `claim-lifecycle.dmn` | DMN 1.3 XML | Two decision tables: `DetermineClaimTransition` (run status progression) and `DetermineOBXResolution` (authoritative OBX row selection for synthesis) |
| `erd-full.mermaid` | Mermaid ERD | YottaDB global key schema — RUN, CLAIM, MSG (header/PID/OBX/NTE), OBX_CODE, AGENT, ACK_LOG globals with relationships |

> Render `erd-full.mermaid` at [mermaid.live](https://mermaid.live)
> Load `claim-lifecycle.dmn` in [Camunda Modeler](https://camunda.com/download/modeler/) or [demo.bpmn.io](https://demo.bpmn.io)

---

### api/
API specification.

| File | Format | Contents |
|---|---|---|
| `openapi.yaml` | OpenAPI 3.1 | 15 REST endpoints across Claims, Runs, Verdicts, Audit, and System tags |

> Paste into [editor.swagger.io](https://editor.swagger.io) for interactive docs.

---

### architecture/
System-level views.

| File | Format | Contents |
|---|---|---|
| `c4-containers.mermaid` | Mermaid C4Container | All 10 agent bundles, orchestrator, edge adapter, consumer API, external APIs, and inter-service relationships |
| `agent-topology.mermaid` | Mermaid flowchart | Three-phase execution topology — sequential ingestion, parallel fan-out, sequential synthesis — with MCP and Mirth planes distinguished |
| `mcp-topology.mermaid` | Mermaid flowchart | Hub-and-spoke MCP control plane — orchestrator as sole client, all subagents as servers, pull and push interaction patterns, forbidden subagent-to-subagent connections |
| `dfd-trust-boundaries.mermaid` | Mermaid flowchart | Data flow diagram with external, DMZ, trusted, and LLM trust zones — PII and external API trust annotations |
| `hl7-message-lifecycle.md` | Markdown | End-to-end prose description of how a message is constructed, appended to, routed, finalized, and serialized — including the principle that Mirth is a carrier not a router |

---

### diagrams/sequence/
Behavioural sequence diagrams — runtime flows over time.

| File | Format | Contents |
|---|---|---|
| `seq-orchestrator-pull.mermaid` | Mermaid sequence | Pull pattern — blindspot detector requests COVERAGE_* data; orchestrator fetches from coverage agents and returns consolidated rows |
| `seq-orchestrator-push.mermaid` | Mermaid sequence | Push pattern — orchestrator dispatches coverage-left with a reply channel; agent reasons independently and sends HL7v2 via Mirth |
| `seq-claim-ingestion.mermaid` | Mermaid sequence | Phase 1 — claim submission through ingestion, detection, entity extraction, and check-worthiness gate |
| `seq-agent-fanout.mermaid` | Mermaid sequence | Phase 2 — parallel dispatch and independent execution of claimreview-matcher, three coverage agents, and domain-evidence |
| `seq-synthesis.mermaid` | Mermaid sequence | Phase 3 — blindspot detection (pull pattern) followed by synthesis, OBX resolution, confidence scoring, and verdict emission |
| `seq-edge-serialization.mermaid` | Mermaid sequence | Edge — finalized HL7v2 to FHIR-like JSON transformation, schema validation, Consumer API delivery, and error path |

---

### diagrams/state/
State machine diagrams.

| File | Format | Contents |
|---|---|---|
| `state-claim.mermaid` | Mermaid stateDiagram-v2 | Run lifecycle — INGESTED → ANALYZING → SYNTHESIZED → PUBLISHED (and CANCELLED) with guard conditions and YottaDB annotations |
| `state-obx-result.mermaid` | Mermaid stateDiagram-v2 | OBX result status transitions — P → F, P → X, F → C, C → C — with synthesizer behaviour per terminal state |

---

### features/
Gherkin feature files — executable acceptance test specifications.

| File | Scenarios | Coverage |
|---|---|---|
| `claim-ingestion.feature` | 13 | Submission validation, ingestion OBX writes, check-worthiness gate, entity extraction, Phase 2 trigger |
| `agent-coordination.feature` | 14 | Hub-and-spoke topology, push pattern, pull pattern, OBX ordering, ACK retry semantics, completion register, orchestrator restart recovery |
| `verdict-synthesis.feature` | 13 | OBX resolution, confidence computation, verdict mapping, ClaimReview override, synthesizer output, run state transition |
| `validation-baseline.feature` | 9 | Per-corpus-category accuracy, swarm vs single-agent baseline, audit log coverage, run latency budget |
| `edge-serialization.feature` | 12 | Trigger conditions, OBX resolution, required JSON fields, schema validation, error path, Consumer API delivery |

> Compatible with `@cucumber/cucumber` and `jest-cucumber`.

---

### requirements/
Non-functional requirements.

| File | Format | Contents |
|---|---|---|
| `nfr.md` | Markdown | 27 NFRs across 8 ISO/IEC 25010 categories using Quality Attribute Scenarios and Planguage — covering performance, reliability, security, maintainability, portability, correctness, auditability, and observability |

---

### infrastructure/
Local development configuration.

| File | Format | Contents |
|---|---|---|
| `docker-compose.yml` | Docker Compose v3 | Full local stack — 33 containers: 10 agent processes, 11 YottaDB instances, 11 Mirth instances, orchestrator, consumer-api |
| `docker-topology.mermaid` | Mermaid flowchart | Container dependency graph, port bindings (host-exposed vs internal-only), MCP connections, Mirth MLLP routing, startup order |

> **Entry point:** `docker compose up`
> Consumer API available at `http://localhost:8000`
> Mirth orchestrator admin at `https://localhost:8443` (dev only)
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
| Inter-agent wire format | HL7v2 pipe-delimited (ORU^R01) | ADR-001 |
| Agent state storage | YottaDB (MUMPS globals) | ADR-002 |
| Log structure | Append-only OBX rows, never overwritten | ADR-003 |
| HL7v2 construction | Tool-based — LLMs never generate raw HL7v2 | ADR-004 |
| Epistemic state carrier | OBX.11 result status (P/F/C/X) | ADR-005 |
| Edge serialization | Mirth adapter — HL7v2 → FHIR-like JSON | ADR-006 |
| HL7v2 transport | Mirth Connect (carrier, not router) | ADR-007 |
| Validation baseline | 50-claim PolitiFact corpus, 10 non-indexed claims | ADR-008 |
| MCP topology | Orchestrator-as-hub, no subagent-to-subagent | ADR-009 |
| Orchestrator state | Stateless — reads agent YottaDB via MCP on demand | ADR-010 |

---

## Two Communication Planes

The system uses two distinct communication planes that fail independently:

| Plane | Protocol | Purpose | Failure consequence |
|---|---|---|---|
| MCP control | MCP over TCP | Orchestrator dispatches tasks, reads state, receives data requests from agents | In-flight task lost; recoverable via orchestrator restart |
| Mirth data | MLLP / HL7v2 | Agents send reasoning findings; ACKs signal delivery | Retried up to 3× on AE; OBX data already in YottaDB is safe |

---

## Validation Strategy

The system's output is validated against a curated 50-claim PolitiFact
corpus. The corpus is divided into five categories of 10 claims each:

| Category | Description | Key metric |
|---|---|---|
| TRUE_MOSTLY_TRUE | Known true claims | ≥ 7/10 correct alignment |
| FALSE_PANTS_FIRE | Known false claims | ≥ 7/10 correct alignment |
| HALF_TRUE | Ambiguous claims | ≥ 5/10 in adjacent tiers |
| CLAIMREVIEW_INDEXED | Claims in Google Fact Check Tools | ≥ 8/10 match ClaimReview verdict |
| NOT_CLAIMREVIEW_INDEXED | Claims not yet in ClaimReview | Swarm beats single-agent by ≥ 20pp |

The fifth category — claims not yet indexed in ClaimReview — is the
primary proof-of-value test. A single agent calling ClaimReview returns
no match for these claims. The swarm's parallel coverage analysis and
domain evidence agents provide signal unavailable to a monolithic approach.

---

## The Audit Trail

Every published verdict includes an `audit_log_ref` pointing to a
retained `.hl7` file in YottaDB. This file contains every OBX row
written by every agent during the run, in sequence order, with full
attribution. The JSON verdict delivered to consumers is derived from
this file and is disposable. The HL7v2 log is authoritative.

This interpretability is architecturally guaranteed by the wire format —
not bolted on after the fact.
