## Why

The swarm-reasoning system needs a backend API to accept claims from the frontend, manage session lifecycle, relay real-time progress via SSE, persist verdicts and citations, and serve audit data. The architecture specifies NestJS with Clean Architecture (ADR-015), PostgreSQL with TypeORM (ADR-017), and integration points to Temporal (control plane) and Redis Streams (data plane). Without this backend, the frontend has no API to talk to, Temporal workflows have no trigger, and verdicts have nowhere to persist.

## What Changes

- Scaffold a NestJS application with Clean Architecture layers: Domain, Application, Interface Adapters, Infrastructure
- Define domain entities: Session, Claim, Run, Verdict, Citation, ProgressEvent
- Implement application use cases: SubmitClaimUseCase, GetSessionUseCase, FinalizeSessionUseCase, CleanupExpiredSessionsUseCase, StreamProgressUseCase
- Create interface adapter layer: ClaimController, SessionController, VerdictController, SSE controller, repository interfaces, VerdictPresenter
- Build infrastructure implementations: TypeOrmSessionRepository, TypeOrmVerdictRepository, TypeOrmCitationRepository, TemporalClientAdapter, RedisStreamAdapter, StaticHtmlRenderer, S3SnapshotStore
- Define TypeORM entities and migrations for PostgreSQL
- Implement 7 REST endpoints per OpenAPI spec (POST /sessions, POST /sessions/:id/claims, GET /sessions/:id, GET /sessions/:id/events, GET /sessions/:id/verdict, GET /sessions/:id/observations, GET /health)
- Implement session lifecycle: active -> frozen -> expired with 3-day TTL cleanup

## Capabilities

### New Capabilities
- `session-management`: Session lifecycle (create, freeze, expire, cleanup), state machine enforcement, TTL-based expiration
- `claim-submission`: Claim validation, run initiation via Temporal, 202 Accepted response with session state
- `verdict-retrieval`: Verdict with citations, static HTML snapshot rendering, S3 upload for frozen sessions

### Modified Capabilities

## Impact

- **New service**: `backend/` directory with NestJS application
- **Infrastructure**: PostgreSQL container, TypeORM migrations
- **Dependencies**: @nestjs/core, @nestjs/typeorm, typeorm, pg, ioredis, @temporalio/client
- **Downstream**: Frontend consumes all 7 endpoints; Agent Service receives Temporal workflow triggers
