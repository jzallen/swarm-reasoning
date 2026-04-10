---
status: accepted
date: 2026-04-10
deciders: []
---

# ADR-0014: Three-Service Architecture

## Context and Problem Statement

The system requires separation of concerns between the user-facing web interface, API/business logic, and AI agent execution. A monolithic architecture would couple LLM processing to the web server, blocking requests during long-running agent workflows. Each concern has different scaling characteristics: the frontend serves static assets, the API handles request routing and persistence, and the agent service performs compute-intensive LLM calls that can run for minutes per claim.

## Decision Drivers

- LLM agent workflows are long-running (minutes per claim) and must not block API request handling
- Each tier has different scaling profiles: static assets (CDN), API (request concurrency), agents (GPU/CPU-bound LLM calls)
- TypeScript is strongest for API development with NestJS; Python is strongest for LangChain/LLM tooling
- Independent deployability reduces blast radius of changes

## Considered Options

1. **Monolith** -- Single NestJS application with embedded Python agent calls via child processes or FFI. Simplest deployment but LLM calls block the event loop, and mixing Python into a Node process is fragile.
2. **Two services** -- NestJS handles API and frontend via SSR, separate Python agent service. Reduces the coupling but ties frontend rendering to API availability and scaling.
3. **Three services** -- Dedicated frontend (React/TypeScript, Vite, served via S3+CloudFront), NestJS backend API (Clean Architecture, TypeORM, PostgreSQL), Python agent service (LangChain, Temporal workers).

## Decision Outcome

Chosen option: "Three services", because it isolates LLM-heavy processing from the web tier, allows independent scaling of each concern, and uses each language where it is strongest.

- **Frontend**: React/TypeScript SPA built with Vite, deployed to S3 with CloudFront distribution. No server-side rendering; the API provides all dynamic data.
- **Backend API**: NestJS with Clean Architecture (ADR-0015). Accepts claim submissions, starts Temporal workflows (ADR-0016), relays SSE progress events to the frontend, and serves static verdict snapshots. PostgreSQL via TypeORM for persistence (ADR-0017).
- **Agent Service**: Python with LangChain. Runs Temporal activity workers that execute the 11 specialized agents. Publishes observations to Redis Streams (data plane unchanged from ADR-0012).

The backend is the gateway between frontend and agent service. The frontend never communicates directly with the agent service.

### Consequences

- Good, because agent failures (LLM timeouts, rate limits, crashes) do not affect API availability
- Good, because each service can scale independently -- the agent service can add workers without touching the API
- Good, because language-appropriate tooling: TypeScript/NestJS for structured API development, Python for LangChain and LLM ecosystem
- Bad, because three separate deployments to manage, with CI/CD pipelines for each
- Bad, because cross-service contract maintenance requires shared schema definitions or contract tests
- Neutral, because Docker Compose unifies local development into a single `docker compose up`

## More Information

- ADR-0015: NestJS Backend with Clean Architecture
- ADR-0016: Temporal.io for Agent Orchestration
- ADR-0017: PostgreSQL with TypeORM for Persistence
- ADR-0012: Redis Streams Transport (data plane unchanged)
