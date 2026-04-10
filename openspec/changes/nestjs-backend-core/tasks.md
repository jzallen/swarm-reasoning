## 1. Project Setup

- [ ] 1.1 Initialize NestJS project in `backend/` with `@nestjs/cli`
- [ ] 1.2 Configure `tsconfig.json` with strict mode and path aliases for each layer
- [ ] 1.3 Create directory structure: `src/domain/`, `src/application/`, `src/adapters/`, `src/infrastructure/`
- [ ] 1.4 Install dependencies: @nestjs/typeorm, typeorm, pg, ioredis, @temporalio/client, @nestjs/schedule
- [ ] 1.5 Configure ESLint and Prettier per project code style
- [ ] 1.6 Create `src/app.module.ts` with imports for SessionModule, VerdictModule, CitationModule, StreamModule
- [ ] 1.7 Add environment configuration module for DATABASE_URL, REDIS_URL, TEMPORAL_ADDRESS

## 2. Domain Entities

- [ ] 2.1 Implement `Session` domain entity with sessionId (UUID), status, claim, createdAt, frozenAt, expiresAt, snapshotUrl
- [ ] 2.2 Implement `SessionStatus` enum: active, frozen, expired
- [ ] 2.3 Implement session state transition validation (active -> frozen -> expired)
- [ ] 2.4 Implement `Claim` value object with claimText, sourceUrl, sourceDate, validation rules
- [ ] 2.5 Implement `Run` domain entity with runId, sessionId, status, phase, createdAt, completedAt
- [ ] 2.6 Implement `RunStatus` enum: pending, ingesting, analyzing, synthesizing, completed, cancelled, failed
- [ ] 2.7 Implement run state transition validation per state machine
- [ ] 2.8 Implement `Verdict` domain entity with verdictId, factualityScore, ratingLabel, narrative, signalCount, finalizedAt
- [ ] 2.9 Implement `RatingLabel` enum: true, mostly-true, half-true, mostly-false, false, pants-on-fire
- [ ] 2.10 Implement `Citation` domain entity with sourceUrl, sourceName, agent, observationCode, validationStatus, convergenceCount
- [ ] 2.11 Implement `ValidationStatus` enum: live, dead, redirect, soft-404, timeout, not-validated
- [ ] 2.12 Implement `ProgressEvent` domain entity with runId, agent, phase, type, message, timestamp

## 3. Application Use Cases

- [ ] 3.1 Define `SessionRepository` interface: save, findById, findExpiredSessions, delete
- [ ] 3.2 Define `VerdictRepository` interface: save, findBySessionId
- [ ] 3.3 Define `CitationRepository` interface: saveMany, findByVerdictId
- [ ] 3.4 Define `TemporalClient` interface: startClaimVerificationWorkflow, getWorkflowStatus
- [ ] 3.5 Define `StreamReader` interface: readProgress, readObservations
- [ ] 3.6 Define `SnapshotStore` interface: upload, delete
- [ ] 3.7 Implement `CreateSessionUseCase`: generate UUID v4 session ID, persist new session with status `active` to PostgreSQL, return session DTO
- [ ] 3.8 Unit test `CreateSessionUseCase`: verify UUID generation, session persistence call, returned DTO fields, and status is `active`
- [ ] 3.9 Wire `POST /sessions` controller method to `CreateSessionUseCase`
- [ ] 3.10 Implement `SubmitClaimUseCase`: validate claim, create run for existing session, start Temporal workflow, return session
- [ ] 3.11 Implement `GetSessionUseCase`: load session by ID, include verdict if completed, include snapshotUrl if frozen
- [ ] 3.12 Implement `FinalizeSessionUseCase`: persist verdict and citations, freeze session, render static HTML, upload snapshot
- [ ] 3.13 Implement `StreamProgressUseCase`: subscribe to progress stream, yield SSE-formatted events
- [ ] 3.14 Implement `GetObservationsUseCase`: read all agent observation streams for a run via StreamReader
- [ ] 3.15 Implement `CleanupExpiredSessionsUseCase`: query expired sessions, delete snapshots, delete database rows

## 4. Interface Adapters (Controllers)

- [ ] 4.1 Implement `SessionController` with POST /sessions endpoint (createSession)
- [ ] 4.2 Implement `SessionController` with GET /sessions/:sessionId endpoint (getSession)
- [ ] 4.3 Implement `ClaimController` with POST /sessions/:sessionId/claims endpoint (submitClaim)
- [ ] 4.4 Implement `EventController` with GET /sessions/:sessionId/events SSE endpoint (streamProgress)
- [ ] 4.5 Implement `VerdictController` with GET /sessions/:sessionId/verdict endpoint (getVerdict)
- [ ] 4.6 Implement `ObservationController` with GET /sessions/:sessionId/observations endpoint (getObservations)
- [ ] 4.7 Implement `HealthController` with GET /health endpoint (healthCheck)
- [ ] 4.8 Implement `VerdictPresenter` to format verdict + citations response per OpenAPI schema
- [ ] 4.9 Implement request validation DTOs with class-validator decorators
- [ ] 4.10 Implement global exception filter for consistent ErrorResponse format
- [ ] 4.11 Implement session-not-found guard returning 404

## 5. TypeORM Infrastructure

- [ ] 5.1 Create TypeORM entity `SessionEntity` with table mapping and column decorators
- [ ] 5.2 Create TypeORM entity `RunEntity` with session foreign key
- [ ] 5.3 Create TypeORM entity `VerdictEntity` with run foreign key
- [ ] 5.4 Create TypeORM entity `CitationEntity` with verdict foreign key
- [ ] 5.5 Create initial migration: create sessions, runs, verdicts, citations tables
- [ ] 5.6 Add indexes: sessions(status, frozenAt), runs(sessionId), verdicts(runId), citations(verdictId)
- [ ] 5.7 Implement `TypeOrmSessionRepository` mapping between domain Session and SessionEntity
- [ ] 5.8 Implement `TypeOrmVerdictRepository` mapping between domain Verdict and VerdictEntity
- [ ] 5.9 Implement `TypeOrmCitationRepository` mapping between domain Citation and CitationEntity
- [ ] 5.10 Implement `TypeOrmRunRepository` mapping between domain Run and RunEntity
- [ ] 5.11 Configure TypeORM module with PostgreSQL connection and entity registration
- [ ] 5.12 Configure migration run-on-startup for development environment

## 6. Redis and Temporal Adapters

- [ ] 6.1 Implement `RedisStreamAdapter` (implements StreamReader): XREAD for progress stream, XRANGE for observation streams
- [ ] 6.2 Implement SSE formatting: map progress stream entries to `event: progress`, `event: verdict`, `event: close`
- [ ] 6.3 Implement `TemporalClientAdapter` (implements TemporalClient): connect to Temporal, start workflow, query status
- [ ] 6.4 Configure Temporal client connection with TEMPORAL_ADDRESS environment variable
- [ ] 6.5 Implement `StaticHtmlRenderer`: render verdict + citations as self-contained HTML page
- [ ] 6.6 Implement `S3SnapshotStore` (implements SnapshotStore): upload HTML to S3, generate presigned URL
- [ ] 6.7 Implement `LocalSnapshotStore` for development (writes to filesystem)

## 7. Health Check

- [ ] 7.1 Implement PostgreSQL health check via TypeORM connection query
- [ ] 7.2 Implement Redis health check via PING command
- [ ] 7.3 Implement Temporal health check via client connection status
- [ ] 7.4 Aggregate health into HealthResponse: healthy (all up), degraded (partial), unhealthy (critical down)

## 8. NestJS Module Wiring

- [ ] 8.1 Create `SessionModule` providing SessionController, ClaimController, SubmitClaimUseCase, GetSessionUseCase
- [ ] 8.2 Create `VerdictModule` providing VerdictController, FinalizeSessionUseCase, VerdictPresenter
- [ ] 8.3 Create `CitationModule` providing CitationRepository
- [ ] 8.4 Create `StreamModule` providing EventController, ObservationController, StreamProgressUseCase, GetObservationsUseCase
- [ ] 8.5 Create `InfrastructureModule` providing TypeORM repositories, RedisStreamAdapter, TemporalClientAdapter
- [ ] 8.6 Register CleanupExpiredSessionsUseCase as a NestJS cron job (runs every hour)

## 9. Tests

- [ ] 9.1 Unit test: Session domain entity state transitions (valid and invalid)
- [ ] 9.2 Unit test: Run domain entity state transitions (valid and invalid)
- [ ] 9.3 Unit test: Claim value object validation (empty text, max length, valid URLs)
- [ ] 9.4 Unit test: SubmitClaimUseCase with mocked repositories and Temporal client
- [ ] 9.5 Unit test: GetSessionUseCase with mocked SessionRepository
- [ ] 9.6 Unit test: FinalizeSessionUseCase with mocked repositories, renderer, snapshot store
- [ ] 9.7 Unit test: CleanupExpiredSessionsUseCase with mocked repositories and snapshot store
- [ ] 9.8 Unit test: VerdictPresenter formatting matches OpenAPI schema
- [ ] 9.9 Integration test: POST /sessions creates session and returns 201
- [ ] 9.10 Integration test: POST /sessions/:id/claims returns 202 and starts workflow
- [ ] 9.11 Integration test: GET /sessions/:id returns session with verdict when completed
- [ ] 9.12 Integration test: GET /sessions/:id/verdict returns 404 when no verdict exists
- [ ] 9.13 Integration test: GET /health returns service status
- [ ] 9.14 Integration test: TypeORM repositories CRUD operations against test database
- [ ] 9.15 E2E test: full claim submission through verdict retrieval with mocked Temporal
