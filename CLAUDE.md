# CLAUDE.md

## Project Overview

**swarm-reasoning** — Multi-agent fact-checking system using structured JSON observations streamed via Redis Streams as inter-agent communication. Eleven specialized agents coordinate via swarm reasoning to validate claims against a PolitiFact corpus. Confidence-scored verdicts are produced through three-phase execution: sequential ingestion, parallel fan-out, sequential synthesis. A chat-based frontend lets users submit claims, watch agent progress via SSE, and receive annotated verdicts with full source citations.

## Tech Stack

- **Python 3.11** — Agent logic (LangChain), Temporal workers
- **TypeScript / Node 20** — NestJS backend API (Clean Architecture, TypeORM), React frontend (Vite)
- **PostgreSQL** — Persistent storage for claims, sessions, verdicts, citations (Aurora Serverless v2 in prod)
- **Redis Streams** — Append-only observation log, inter-agent data plane (dev); Kafka graduation path for production (ADR-012)
- **Temporal.io** — Durable workflow orchestration; replaces MCP as control plane (ADR-016)
- **Docker Compose** — Local development stack
- **Cloudflare** — Edge proxy, DDoS protection, SSL termination, rate limiting (ADR-020)
- **AWS ECS Fargate** — Production deployment, scale-to-zero (ADR-020)
- **Gherkin / Cucumber** — BDD acceptance tests (67 scenarios across 5 feature files)

## Architecture (Key Decisions)

ADRs in `docs/decisions/` as individual MADR v3.0 files (ADR-0003 through ADR-0021).

- **Three-service architecture** — Frontend (React/TS), Backend API (NestJS), Agent Service (Python/LangChain) (ADR-014)
- **NestJS Clean Architecture** — Domain → Application (Use Cases) → Interface Adapters → Infrastructure (ADR-015)
- **Temporal.io orchestration** — Orchestrator is a Temporal workflow; each agent is a Temporal activity worker (ADR-016)
- **PostgreSQL + TypeORM** — Persistent storage with Aurora Serverless v2 for prod scale-to-zero (ADR-017)
- **SSE relay** — Backend subscribes to Redis progress stream and relays to frontend via Server-Sent Events (ADR-018)
- **Static HTML verdict snapshots** — Frozen sessions served as self-contained HTML with verdict/chat toggle, 3-day TTL (ADR-019)
- **JSON observation schema** — Typed observations with epistemic status (P/F/C/X), published to Redis Streams (ADR-011)
- **Tool-based observation construction** — LLMs never generate raw observations; tools enforce schema validity (ADR-004)
- **Append-only observation log** — Observations are never overwritten; the Redis Streams log is authoritative (ADR-003)
- **Two communication planes** — Temporal control plane + Redis Streams data plane, fail independently (ADR-013)
- **Transport abstraction** — `ReasoningStream` interface decouples agents from backend; Redis for dev, Kafka for prod (ADR-012)

## Project Structure

```
services/
  agent-service/           — Python agent workers (LangChain, Temporal activities)
  backend/                 — NestJS API server (Clean Architecture, TypeORM)
  frontend/                — React SPA (Vite)
docs/
  decisions/               — 17 MADR v3.0 ADR files (ADR-0003 through ADR-0021) + index + template
  domain/                  — Observation schema spec, OBX code registry, claim lifecycle DMN, ERD, SBVR business rules
  api/openapi.yaml         — REST endpoint paths (Sessions, Verdicts, Audit, System)
  architecture/            — System architecture diagram, agent topology, DFD, stream lifecycle, docker topology
  diagrams/sequence/       — Mermaid sequence diagrams (ingestion, fanout, synthesis, etc.)
  diagrams/state/          — Claim lifecycle + observation result status state machines
  features/                — 5 Gherkin files (67 scenarios)
  requirements/nfrs/       — 32 individual NFR files (SEI QAS + Planguage) + index + template
deploy/
  cloudflare/              — DNS, SSL, cache, and rate-limit rule configs
  ecs/                     — ECS task definitions, CloudFormation templates
  k8s/                     — Helm chart for minikube demo
docker-compose.yml           — Full local development stack (8 services)
.openspec/                   — OpenSpec change tracking (hidden directory)
```

## The 11 Agents

Agents communicate via JSON observations published to Redis Streams. Each owns a subset of codes from `docs/domain/obx-code-registry.json`. Each agent runs as a Temporal worker in the Agent Service.

1. **ingestion-agent** — Claim intake, entity extraction, check-worthiness gate
2. **claim-detector** — Check-worthiness scoring, claim normalization
3. **entity-extractor** — Named entity recognition (persons, orgs, dates, locations, statistics)
4. **claimreview-matcher** — Google Fact Check Tools API lookup
5. **coverage-left** — Left-leaning source analysis
6. **coverage-center** — Centrist source analysis
7. **coverage-right** — Right-leaning source analysis
8. **domain-evidence** — Domain-specific evidence gathering (CDC, SEC, WHO, PubMed, etc.)
9. **source-validator** — Link extraction, URL validation, source convergence, citation aggregation
10. **blindspot-detector** — Identifies coverage gaps across agents
11. **synthesizer** — Observation resolution, confidence scoring, verdict emission with annotated sources

## Observation Stream Format

Each agent's reasoning session follows: `START → OBS[1..N] → STOP`

- **`status` field** carries epistemic state: `P` (preliminary), `F` (final), `C` (corrected), `X` (cancelled)
- Full schema spec: `docs/domain/observation-schema-spec.md`
- Agent identity is in the `agent` field of each observation
- Stream key format: `reasoning:{runId}:{agent}`
- Progress stream: `progress:{runId}` — user-friendly messages relayed via SSE

## Code Style

- **Python**: Ruff formatter and linter (configured in devcontainer)
- **TypeScript**: Prettier + ESLint
- Format-on-save is enabled for both languages

## Git Conventions

- **Conventional Commits** format: `<type>(<scope>): <description>`
- Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `perf`, `build`, `style`
- Subject line: imperative mood, max 72 chars, no trailing period
- Base commit messages on the **actual diff**, not assumptions or chat context
- **Never** append Claude session URLs, attribution, or AI disclaimers to commit messages
- If multiple logical changes exist, prefer separate atomic commits
- Branch naming: `<type>/<short-description>`

## Environment

- Entry point: `docker compose up`
- Backend API: `http://localhost:3000`
- Frontend: `http://localhost:5173` (Vite dev server)
- Temporal UI: `http://localhost:8233`
- Redis: `redis://localhost:6379` (dev only)
- PostgreSQL: `postgresql://localhost:5432/swarm` (dev only)
- Required env vars: `ANTHROPIC_API_KEY`, `GOOGLE_FACTCHECK_API_KEY`, `NEWSAPI_KEY`
