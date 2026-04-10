---
status: accepted
date: 2026-04-10
deciders: []
---

# ADR-0015: NestJS Backend with Clean Architecture

## Context and Problem Statement

The backend API must handle claim submission, session management, SSE relay, static HTML rendering, and data persistence. A standard NestJS layered approach (controller -> service -> repository) tends to accumulate business logic mixed with framework concerns, making it difficult to test domain rules in isolation. A layered architecture with explicit dependency rules prevents framework coupling and keeps business logic testable.

## Decision Drivers

- Business logic must be testable without framework dependencies (NestJS, TypeORM)
- Repository interfaces must support test doubles for unit testing use cases
- NestJS module structure should map naturally to bounded contexts
- Dependencies must point inward: infrastructure depends on domain, never the reverse

## Considered Options

1. **Standard NestJS layering** -- Controller -> Service -> Repository. Simple and conventional, but services accumulate business logic mixed with framework concerns. Testing requires mocking NestJS internals.
2. **Clean Architecture** -- Domain (entities), Application (use cases), Interface Adapters (controllers, repository interfaces), Infrastructure (TypeORM repos, Redis adapter, Temporal client). More boilerplate but domain logic is framework-independent.
3. **Hexagonal / Ports-and-Adapters** -- Similar separation to Clean Architecture with ports (interfaces) and adapters (implementations). The distinction from Clean Architecture is largely academic in a NestJS context.

## Decision Outcome

Chosen option: "Clean Architecture", because it provides clear dependency rules (dependencies point inward) and maps naturally to NestJS module structure.

**Domain Layer** -- Entities with no framework dependencies:
- `Claim` -- submitted claim text, source, metadata
- `Session` -- reasoning session lifecycle, status tracking
- `Verdict` -- final verdict with confidence score and rating
- `Citation` -- source citations supporting the verdict
- `ProgressEvent` -- SSE-compatible progress updates during agent execution

**Application Layer** -- Use cases depending only on domain and repository interfaces:
- `SubmitClaimUseCase` -- validates claim, creates session, triggers Temporal workflow
- `StreamProgressUseCase` -- subscribes to Redis Streams, emits SSE events to client
- `FinalizeSessionUseCase` -- processes synthesizer verdict, persists final results
- `GetSessionUseCase` -- retrieves session with verdict and citations
- `CleanupExpiredSessionsUseCase` -- removes stale sessions beyond retention period

**Interface Adapters Layer** -- Controllers, presenters, repository interfaces:
- REST controllers for claims, sessions, verdicts
- SSE controller for progress streaming
- Repository interfaces (`SessionRepository`, `VerdictRepository`, `CitationRepository`)

**Infrastructure Layer** -- Framework and external service implementations:
- `TypeOrmSessionRepository`, `TypeOrmVerdictRepository`, `TypeOrmCitationRepository`
- `RedisStreamAdapter` -- reads observation streams for SSE relay
- `TemporalClientAdapter` -- starts and signals Temporal workflows
- `StaticHtmlRenderer` -- renders verdict pages for sharing/SEO
- `S3SnapshotStore` -- uploads static HTML snapshots

NestJS modules map 1:1 to bounded contexts: `SessionModule`, `VerdictModule`, `CitationModule`, `StreamModule`.

### Consequences

- Good, because domain logic has zero framework imports and can be tested with plain unit tests
- Good, because use cases are independently testable with repository interface test doubles
- Good, because repository interfaces enable swapping persistence without touching business logic
- Bad, because more files and indirection than standard NestJS (entity + use case + interface + implementation per concern)
- Neutral, because TypeORM entities live in the infrastructure layer as separate classes from domain entities

## More Information

- ADR-0014: Three-Service Architecture (backend is one of three services)
- ADR-0017: PostgreSQL with TypeORM for Persistence (infrastructure layer details)
