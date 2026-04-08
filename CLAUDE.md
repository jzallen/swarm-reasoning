# CLAUDE.md

## Project Overview

**hl7-agent-factchecker** — Multi-agent fact-checking system using HL7v2 (ORU^R01) as inter-agent wire format. Ten specialized agents coordinate via swarm reasoning to validate claims against a PolitiFact corpus. Confidence-scored verdicts are produced through three-phase execution: sequential ingestion, parallel fan-out, sequential synthesis.

## Tech Stack

- **Python 3.11** — Agent logic, orchestration (LangChain), API (FastAPI)
- **TypeScript / Node 20** — CLI tooling, API layer
- **YottaDB** — MUMPS-native storage for agent state and HL7v2 audit logs
- **Mirth Connect** — HL7v2 transport (MLLP); carrier, not router
- **MCP** — Control plane between orchestrator (hub) and agent servers (spokes)
- **Docker Compose** — 33-container local stack
- **Gherkin / Cucumber** — BDD acceptance tests (52 scenarios across 5 feature files)

## Architecture (Key Decisions)

Detailed ADRs in `docs/decisions/adrs.md` (ADR-001 through ADR-010).

- **HL7v2 wire format** — Line-oriented, self-delimiting; chosen over JSON for native result status, streaming, and YottaDB alignment (ADR-001)
- **Tool-based HL7v2 construction** — LLMs never generate raw HL7v2; tools enforce segment validity (ADR-004)
- **Append-only OBX log** — OBX rows are never overwritten; the HL7v2 log is authoritative, JSON verdicts are disposable (ADR-003)
- **Hub-and-spoke MCP** — Orchestrator is the sole MCP client; no subagent-to-subagent connections (ADR-009)
- **Stateless orchestrator** — Reads agent state via MCP on demand; recovers via YottaDB (ADR-010)
- **Two communication planes** — MCP control plane + Mirth data plane, fail independently

## Project Structure

```
docs/
  decisions/adrs.md        — 10 ADRs
  domain/                  — HL7v2 segment spec, OBX code registry (31 codes), claim lifecycle DMN, ERD
  api/openapi.yaml         — 15 REST endpoints (Claims, Runs, Verdicts, Audit, System)
  architecture/            — C4 containers, agent topology, MCP topology, DFD, message lifecycle
  diagrams/sequence/       — 6 Mermaid sequence diagrams (ingestion, fanout, synthesis, etc.)
  diagrams/state/          — Claim lifecycle + OBX result status state machines
  features/                — 5 Gherkin files (52 scenarios)
  requirements/nfr.md      — 27 NFRs (ISO/IEC 25010)
  infrastructure/          — docker-compose.yml, topology diagram
```

## The 10 Agents

Agents communicate via HL7v2 OBX observations. Each owns a subset of codes from `docs/domain/obx-code-registry.json`:

1. **ingestion-agent** — Claim intake, entity extraction, check-worthiness gate
2. **claimreview-matcher** — Google Fact Check Tools API lookup
3. **coverage-left** — Left-leaning source analysis
4. **coverage-center** — Centrist source analysis
5. **coverage-right** — Right-leaning source analysis
6. **domain-evidence** — Domain-specific evidence gathering
7. **blindspot-detector** — Identifies coverage gaps (uses MCP pull pattern)
8. **synthesizer** — OBX resolution, confidence scoring, verdict emission
9. **edge-serializer** — HL7v2 to FHIR-like JSON transformation
10. **consumer-api** — FastAPI REST layer for external consumers

## HL7v2 Message Format

Messages follow: `MSH → PID → OBX[1..N] → NTE[0..M]`

- **OBX.11 result status** carries epistemic state: `P` (preliminary), `F` (final), `C` (corrected), `X` (cancelled)
- Full segment spec: `docs/domain/hl7-segment-spec.md`
- Agent identity is in `MSH.3` (sending application)
- Message control ID format: `{run_id}-MSG{seq}`

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

- Entry point: `docker compose -f docs/infrastructure/docker-compose.yml up`
- Consumer API: `http://localhost:8000`
- Mirth admin: `https://localhost:8443` (dev only)
- Required env vars: `ANTHROPIC_API_KEY`, `GOOGLE_FACTCHECK_API_KEY`, `NEWSAPI_KEY`
