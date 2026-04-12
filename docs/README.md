# swarm-reasoning -- Architecture & Design Documentation

**Version:** 0.4.0
**Project:** Multi-agent fact-checking system using structured JSON observations
streamed via Redis Streams as inter-agent communication. Eleven coordinating
agents produce confidence-scored verdicts against a PolitiFact validation
corpus through three-phase swarm reasoning. A chat-based frontend lets users
submit claims, watch agent progress via SSE, and receive annotated verdicts
with full source citations.

**Stack:** NestJS (Backend API) . React/TypeScript (Frontend, Vite) . Temporal.io (Orchestration) .
PostgreSQL/TypeORM (Persistence, Aurora Serverless v2 in prod) . Redis Streams (Data Plane) .
LangChain (Agent Logic) . Docker Compose (Local Dev) . ECS Fargate (Production) . Cloudflare (Edge)

---

## Three-Service Architecture

| Service | Tech | Role |
|---|---|---|
| **Frontend** | React/TypeScript, Vite | SPA served via S3 + CloudFront. Session creation, SSE progress display, static verdict snapshots with verdict/chat toggle. |
| **Backend API** | NestJS, TypeORM, PostgreSQL | Clean Architecture (ADR-0015). Accepts claim submissions, starts Temporal workflows, relays SSE progress events, serves static HTML verdict snapshots. |
| **Agent Service** | Python, LangChain | Temporal activity workers executing 11 specialized agents. Publishes observations to Redis Streams (data plane). |

---

## The 11 Agents

Agents communicate via JSON observations published to Redis Streams. Each owns a subset of the 36 observation codes from `domain/obx-code-registry.json`. Each agent runs as a Temporal activity worker in the Agent Service.

1. **ingestion-agent** -- Claim intake, entity extraction, check-worthiness gate
2. **claim-detector** -- Check-worthiness scoring, claim normalization
3. **entity-extractor** -- Named entity recognition (persons, orgs, dates, locations, statistics)
4. **claimreview-matcher** -- Google Fact Check Tools API lookup
5. **coverage-left** -- Left-leaning source analysis
6. **coverage-center** -- Centrist source analysis
7. **coverage-right** -- Right-leaning source analysis
8. **domain-evidence** -- Domain-specific evidence gathering (CDC, SEC, WHO, PubMed, etc.)
9. **source-validator** -- URL validation, source convergence scoring, citation aggregation
10. **blindspot-detector** -- Identifies coverage gaps across agents
11. **synthesizer** -- Observation resolution, confidence scoring, verdict emission with annotated sources

---

## Two Communication Planes

The system uses two distinct communication planes that fail independently (ADR-0013):

| Plane | Protocol | Purpose | Failure consequence |
|---|---|---|---|
| Temporal control | Temporal workflows/activities | Orchestrator dispatches tasks, manages agent lifecycle, handles retries and timeouts | Temporal recovers in-flight workflows from durable execution log |
| Redis Streams data | Redis protocol | Agents publish observations; orchestrator consumes via XREADGROUP | Observations already written are safe; unacknowledged messages reclaimable via XPENDING |

---

## Session-Based API

The backend exposes a session-based REST API (see `api/openapi.yaml`):

| Endpoint | Method | Purpose |
|---|---|---|
| `/sessions` | POST | Create a new session |
| `/sessions/:id/claims` | POST | Submit a claim for fact-checking within a session |
| `/sessions/:id` | GET | Retrieve session status and metadata |
| `/sessions/:id/events` | GET (SSE) | Server-Sent Events stream for real-time agent progress |
| `/sessions/:id/verdict` | GET | Retrieve the final verdict with citations |
| `/sessions/:id/observations` | GET | Observation audit log for the session's run |
| `/health` | GET | Health check for backend and dependent services |

Sessions are ephemeral with a 3-day TTL. The backend subscribes to the Redis `progress:{runId}` stream and relays user-friendly messages to the frontend via SSE. Finalized sessions produce static HTML snapshots with a verdict/chat toggle view (ADR-0019).

---

## Document Index

### decisions/
Architecture Decision Records in [MADR v3.0](https://adr.github.io/madr/) format -- one file per decision, YAML frontmatter for machine parsing. 17 ADRs (ADR-0003 through ADR-0021; ADR-0001, 0002, 0006, 0007 were deleted).

| File | Status |
|---|---|
| `index.md` | Index table linking all 17 ADRs |
| `template.md` | MADR v3.0 template for new ADRs |
| `0003-append-only-observation-log.md` | Accepted |
| `0004-tool-based-observation-construction.md` | Accepted |
| `0005-epistemic-status-carrier.md` | Accepted |
| `0008-politifact-validation-corpus.md` | Accepted |
| `0009-hub-and-spoke-mcp-topology.md` | Superseded by ADR-0016 |
| `0010-stateless-orchestrator.md` | Superseded by ADR-0016 |
| `0011-json-observation-schema.md` | Accepted |
| `0012-redis-streams-transport.md` | Accepted |
| `0013-two-communication-planes.md` | Accepted |
| `0014-three-service-architecture.md` | Accepted |
| `0015-nestjs-clean-architecture.md` | Accepted |
| `0016-temporal-agent-orchestration.md` | Accepted |
| `0017-postgresql-typeorm-persistence.md` | Accepted |
| `0018-sse-relay-for-progress.md` | Accepted |
| `0019-static-html-verdict-snapshots.md` | Accepted |
| `0020-cloudflare-aws-ecs-deployment.md` | Accepted |
| `0021-source-validator-agent.md` | Accepted |

---

### domain/
Domain model -- entities, contracts, and business rules.

| File | Format | Contents |
|---|---|---|
| `observation-schema-spec.md` | Markdown | JSON observation schema -- stream message types (START/OBS/STOP), observation fields, value types, epistemic status semantics, correction pattern, Redis Stream key design, delivery acknowledgment, verdict mapping |
| `obx-code-registry.json` | JSON | 36 canonical observation codes across all 11 agents -- code, display, owner agent, value type, units, reference range, description |
| `claim-lifecycle.dmn` | DMN 1.3 XML | Three decision tables: `DetermineRunTransition` (run status progression), `DetermineSessionTransition` (session status progression), and `DetermineObservationResolution` (authoritative observation selection for synthesis) |
| `erd-full.mermaid` | Mermaid ERD | Data model -- RUN, CLAIM, STREAM_ENTRY, OBSERVATION, OBS_CODE, AGENT, CONSUMER_GROUP entities with Redis Stream key design |
| `business-rules.md` | SBVR | Business vocabulary and business rules in SBVR notation |
| `entities/` | Markdown | DDD entity specifications -- Agent, Citation, Claim, Observation, Progress Event, Run, Session, Verdict |

> Render `erd-full.mermaid` at [mermaid.live](https://mermaid.live)
> Load `claim-lifecycle.dmn` in [Camunda Modeler](https://camunda.com/download/modeler/) or [demo.bpmn.io](https://demo.bpmn.io)

---

### api/
API specification.

| File | Format | Contents |
|---|---|---|
| `openapi.yaml` | OpenAPI 3.0.3 | Session-based REST API -- session creation, claim submission, SSE progress streaming, verdict retrieval, observation audit log, health check, static HTML snapshots |

> Paste into [editor.swagger.io](https://editor.swagger.io) for interactive docs.

---

### architecture/
System-level views.

| File | Format | Contents |
|---|---|---|
| `c4-containers.mermaid` | Mermaid C4Container | Three services (frontend, backend API, agent service), all 11 agents, Redis, PostgreSQL, Temporal, external APIs, and inter-service relationships |
| `agent-topology.mermaid` | Mermaid flowchart | Three-phase execution topology -- sequential ingestion, parallel fan-out, sequential synthesis -- with Temporal and Redis Streams planes distinguished |
| `dfd-trust-boundaries.mermaid` | Mermaid flowchart | Data flow diagram with external, DMZ, trusted, and LLM trust zones -- PII and external API trust annotations |
| `observation-stream-lifecycle.md` | Markdown | End-to-end prose description of how observation streams are opened, grown, consumed, and finalized -- including the two-plane principle (Temporal control + Redis Streams data) |

---

### diagrams/sequence/
Behavioural sequence diagrams -- runtime flows over time.

| File | Format | Contents |
|---|---|---|
| `seq-orchestrator-pull.mermaid` | Mermaid sequence | Pull pattern -- blindspot detector requests COVERAGE_* data; orchestrator reads from coverage agent streams via XRANGE and returns consolidated observations |
| `seq-orchestrator-push.mermaid` | Mermaid sequence | Push pattern -- orchestrator dispatches coverage-left; agent reasons independently and publishes observations to its Redis Stream |
| `seq-claim-ingestion.mermaid` | Mermaid sequence | Phase 1 -- claim submission through ingestion, detection, entity extraction, and check-worthiness gate |
| `seq-agent-fanout.mermaid` | Mermaid sequence | Phase 2 -- parallel dispatch and independent execution of claimreview-matcher, three coverage agents, domain-evidence, and source-validator |
| `seq-synthesis.mermaid` | Mermaid sequence | Phase 3 -- blindspot detection (pull pattern) followed by synthesis, observation resolution, confidence scoring, and verdict emission |
| `seq-session-finalization.mermaid` | Mermaid sequence | Session finalization -- backend API reads finalized observations from Redis Streams, aggregates citations, renders static HTML snapshot, transitions session to frozen |

---

### diagrams/state/
State machine diagrams.

| File | Format | Contents |
|---|---|---|
| `state-claim.mermaid` | Mermaid stateDiagram-v2 | Run lifecycle -- pending -> ingesting -> analyzing -> synthesizing -> completed (and cancelled/failed) with guard conditions |
| `state-obx-result.mermaid` | Mermaid stateDiagram-v2 | Observation result status transitions -- P -> F, P -> X, F -> C, C -> C -- with synthesizer behaviour per terminal state |

---

### features/
Gherkin feature files -- executable acceptance test specifications.

| File | Scenarios | Coverage |
|---|---|---|
| `claim-ingestion.feature` | 13 | Submission validation, ingestion observation writes, check-worthiness gate, entity extraction, Phase 2 trigger |
| `agent-coordination.feature` | 16 | Orchestrator topology, push pattern, pull pattern, observation ordering, delivery retry semantics, completion register, orchestrator restart recovery |
| `verdict-synthesis.feature` | 14 | Observation resolution, confidence computation, verdict mapping, ClaimReview override, synthesizer output, run state transition |
| `validation-baseline.feature` | 11 | Per-corpus-category accuracy, swarm vs single-agent baseline, audit log coverage, run latency budget |
| `verdict-publication.feature` | 13 | Trigger conditions, observation resolution, required JSON fields, schema validation, error path, backend API delivery |

> Compatible with `@cucumber/cucumber` and `jest-cucumber`. 65 scenarios total.

---

### requirements/nfrs/
Non-functional requirements -- one file per NFR, Planguage + SEI Quality Attribute Scenario format, YAML frontmatter for machine parsing. 32 NFRs (NFR-001 through NFR-032).

| File | Contents |
|---|---|
| `index.md` | Index table grouped by ISO/IEC 25010 category |
| `template.md` | NFR template (Planguage + SEI QAS) |
| `NFR-001-*` through `NFR-032-*` | 32 NFRs across 8 quality categories: Performance (6), Reliability (5), Security (5), Maintainability (4), Portability (2), Correctness (4), Auditability (2), Observability (4) |

---

### infrastructure/
Local development configuration.

| File | Location | Format | Contents |
|---|---|---|---|
| `docker-compose.yml` | repo root | Docker Compose | Full local stack -- 8 services: frontend, backend, agent-service, temporal, temporal-ui, temporal-db, postgresql, redis |
| `docker-topology.mermaid` | `docs/architecture/` | Mermaid flowchart | Container dependency graph, port bindings (host-exposed vs internal-only), Temporal connections (control plane), Redis Streams (data plane), startup order |

> **Entry point:** `docker compose up`
> Frontend available at `http://localhost:5173` (Vite dev server)
> Backend API available at `http://localhost:3000`
> Temporal UI available at `http://localhost:8233`
> Redis available at `redis://localhost:6379` (dev only)
> PostgreSQL available at `postgresql://localhost:5432/swarm` (dev only)
> Required environment variables: `ANTHROPIC_API_KEY`, `GOOGLE_FACTCHECK_API_KEY`, `NEWSAPI_KEY`

---

## Deployment

| Layer | Technology | Notes |
|---|---|---|
| Edge | Cloudflare | DDoS protection, SSL termination, rate limiting |
| Load balancer | AWS ALB | Routes to ECS services |
| Backend API + Agent Service | AWS ECS Fargate | Scale-to-zero, independent task definitions |
| Frontend | S3 + CloudFront | Static SPA distribution |
| Database | Aurora Serverless v2 (PostgreSQL) | Scale-to-zero persistence |
| Cache / Streams | ElastiCache (Redis) | Data plane in production |

See [ADR-0020](decisions/0020-cloudflare-aws-ecs-deployment.md) for full deployment architecture.

---

## Key Architectural Decisions at a Glance

| Decision | Choice | ADR |
|---|---|---|
| Inter-agent wire format | JSON observation schema | [ADR-0011](decisions/0011-json-observation-schema.md) |
| Observation transport & storage | Redis Streams (dev), Kafka graduation path (prod) | [ADR-0012](decisions/0012-redis-streams-transport.md) |
| Log structure | Append-only observations, never overwritten | [ADR-0003](decisions/0003-append-only-observation-log.md) |
| Observation construction | Tool-based -- LLMs never generate raw observations | [ADR-0004](decisions/0004-tool-based-observation-construction.md) |
| Epistemic state carrier | Observation `status` field (P/F/C/X) | [ADR-0005](decisions/0005-epistemic-status-carrier.md) |
| Validation baseline | 50-claim PolitiFact corpus, 10 non-indexed claims | [ADR-0008](decisions/0008-politifact-validation-corpus.md) |
| Service decomposition | Three services: frontend, backend API, agent service | [ADR-0014](decisions/0014-three-service-architecture.md) |
| Backend architecture | NestJS Clean Architecture | [ADR-0015](decisions/0015-nestjs-clean-architecture.md) |
| Agent orchestration | Temporal.io workflows and activities | [ADR-0016](decisions/0016-temporal-agent-orchestration.md) |
| Persistence | PostgreSQL with TypeORM, Aurora Serverless v2 in prod | [ADR-0017](decisions/0017-postgresql-typeorm-persistence.md) |
| Communication planes | Temporal control + Redis Streams data, fail independently | [ADR-0013](decisions/0013-two-communication-planes.md) |
| Real-time progress | Server-Sent Events relayed from backend API | [ADR-0018](decisions/0018-sse-relay-for-progress.md) |
| Verdict delivery | Static HTML snapshots with ephemeral sessions (3-day TTL) | [ADR-0019](decisions/0019-static-html-verdict-snapshots.md) |
| Deployment | Cloudflare edge proxy, AWS ECS Fargate | [ADR-0020](decisions/0020-cloudflare-aws-ecs-deployment.md) |
| Source validation | Source-validator agent (11th agent) | [ADR-0021](decisions/0021-source-validator-agent.md) |

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

The fifth category -- claims not yet indexed in ClaimReview -- is the
primary proof-of-value test. A single agent calling ClaimReview returns
no match for these claims. The swarm's parallel coverage analysis and
domain evidence agents provide signal unavailable to a monolithic approach.

---

## The Audit Trail

Every published verdict is backed by the complete observation stream
retained in Redis Streams. This includes every observation written by
every agent during the run, in sequence order, with full attribution
via the `agent` field. The static HTML verdict snapshot delivered to
users is a projection of this stream. The observation log is
authoritative.

This interpretability is architecturally guaranteed by the append-only
stream design -- not bolted on after the fact.

---

## Rendering Guide

| Extension | Tool |
|---|---|
| `.mermaid` | [mermaid.live](https://mermaid.live) -- paste and render |
| `.yaml` (OpenAPI) | [editor.swagger.io](https://editor.swagger.io) |
| `.dmn` | [demo.bpmn.io](https://demo.bpmn.io) or Camunda Modeler |
| `.feature` | Any Gherkin-compatible editor (VS Code + Cucumber extension) |
