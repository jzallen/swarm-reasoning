## Context

The swarm-reasoning backend is a NestJS application following Clean Architecture (ADR-015) with PostgreSQL persistence via TypeORM (ADR-017). It serves as the intermediary between the React frontend and the Python agent service. The backend starts Temporal workflows, subscribes to Redis Streams for SSE relay, and persists all session/verdict/citation data to PostgreSQL. The OpenAPI spec defines 7 endpoints across 4 tags: Sessions, Verdicts, Observations, System.

## Goals / Non-Goals

**Goals:**
- NestJS project with four Clean Architecture layers and strict dependency direction (inward only)
- NestJS modules mapping 1:1 to bounded contexts: SessionModule, VerdictModule, CitationModule, StreamModule
- TypeORM entities and migrations for Session, Claim, Run, Verdict, Citation tables
- All 7 REST endpoints from the OpenAPI spec
- SSE endpoint that relays progress events from Redis Streams
- Health check aggregating Temporal, PostgreSQL, and Redis connectivity
- Session lifecycle management with TTL-based cleanup

**Non-Goals:**
- Authentication or authorization (not required for prototype per OpenAPI spec)
- Frontend implementation (separate slice)
- Temporal workflow/activity definitions (separate slice: temporal-workflow-integration)
- Agent logic or LLM integration
- Production deployment configuration (separate slice)

## Decisions

### 1. Clean Architecture with four layers
Domain entities have zero framework imports. Application use cases depend only on domain and repository interfaces. Infrastructure implements the interfaces. This matches ADR-015 exactly.

**Alternative considered:** Standard NestJS controller-service-repository. Rejected per ADR-015 -- business logic becomes coupled to framework.

### 2. Separate TypeORM entities from domain entities
Domain entities are plain TypeScript classes in the domain layer. TypeORM entities with decorators live in the infrastructure layer. Repositories map between them. This keeps the domain layer framework-free.

**Alternative considered:** Single entity class with TypeORM decorators. Rejected -- violates Clean Architecture dependency rule.

### 3. Repository interface pattern
Repository interfaces (SessionRepository, VerdictRepository, CitationRepository) are defined in the interface adapters layer. TypeORM implementations are in infrastructure. NestJS DI injects implementations at runtime.

### 4. SSE via Redis Stream subscription
The StreamProgressUseCase subscribes to `progress:{runId}` using XREAD in blocking mode. Events are mapped to SSE format and pushed to the client. The connection closes on `verdict` or `close` event types.

### 5. CreateSessionUseCase
`POST /sessions` is handled by `CreateSessionUseCase`. It generates a UUID v4 session ID, persists a new Session to PostgreSQL with status `active`, and returns the session object. This is a lightweight operation that does not start a Temporal workflow -- the workflow is started later by `SubmitClaimUseCase` when a claim is submitted to the session.

### 6. Session freeze and static HTML snapshot
When the synthesizer completes, FinalizeSessionUseCase transitions the session to `frozen`, renders a static HTML snapshot via StaticHtmlRenderer, uploads it to S3 via S3SnapshotStore, and stores the snapshot URL on the session.

### 7. TTL-based session cleanup
CleanupExpiredSessionsUseCase runs on a NestJS cron schedule. It queries for frozen sessions where `frozenAt + 3 days < now()`, deletes the S3 snapshot, and removes all associated database rows.

## Risks / Trade-offs

- **[TypeORM entity mapping overhead]** -- Two entity classes per domain concept adds boilerplate. Acceptable for Clean Architecture benefits.
- **[SSE connection management]** -- Long-lived SSE connections consume server resources. Acceptable at prototype scale; NestJS handles graceful disconnection.
- **[S3 dependency for snapshots]** -- Local development uses a mock or MinIO. Production uses S3. The S3SnapshotStore interface abstracts the difference.
- **[Migration ordering]** -- TypeORM migrations must run before the application starts. The docker-compose health check ensures PostgreSQL is ready.
