## ADDED Requirements

### Requirement: CreateSession integration test validates database persistence
The system SHALL have a test file `tests/use-cases/create-session.integration.spec.ts` that exercises `CreateSessionUseCase` against a pg-mem database.

#### Scenario: Session is created and persisted
- **WHEN** `CreateSessionUseCase.execute()` is called
- **THEN** the returned session SHALL have a valid UUID, Active status, and createdAt timestamp
- **AND** querying the database for that sessionId SHALL return the same session

### Requirement: SubmitClaim integration test validates run creation and session update
The system SHALL have a test file `tests/use-cases/submit-claim.integration.spec.ts` that exercises `SubmitClaimUseCase` against a pg-mem database.

#### Scenario: Claim submitted to active session
- **WHEN** a session exists in Active status and `SubmitClaimUseCase.execute()` is called with valid claim text
- **THEN** the session in the database SHALL have the claim text set
- **AND** a Run entity SHALL exist in the database with Pending status and the session's ID
- **AND** the mock TemporalClient SHALL have been called with the run ID

#### Scenario: Duplicate claim rejected
- **WHEN** a session already has a claim and `execute()` is called again
- **THEN** a ConflictException SHALL be thrown
- **AND** no additional Run SHALL be created in the database

#### Scenario: Frozen session rejected
- **WHEN** a session is in Frozen status and `execute()` is called
- **THEN** an UnprocessableEntityException SHALL be thrown

#### Scenario: Temporal failure transitions run to Failed
- **WHEN** the mock TemporalClient throws on `startClaimVerificationWorkflow`
- **THEN** the Run in the database SHALL have Failed status and a completedAt timestamp

### Requirement: GetSession integration test validates retrieval
The system SHALL have a test file `tests/use-cases/get-session.integration.spec.ts`.

#### Scenario: Existing session retrieved
- **WHEN** a session exists in the database and `GetSessionUseCase.execute()` is called with its ID
- **THEN** the returned session SHALL match the persisted entity

#### Scenario: Missing session throws NotFoundException
- **WHEN** `execute()` is called with a non-existent session ID
- **THEN** a NotFoundException SHALL be thrown

### Requirement: GetVerdict integration test validates verdict with citations
The system SHALL have a test file `tests/use-cases/get-verdict.integration.spec.ts`.

#### Scenario: Verdict retrieved with citations
- **WHEN** a session, run, verdict, and citations exist in the database
- **THEN** `GetVerdictUseCase.execute()` SHALL return the verdict with all associated citations

#### Scenario: No verdict returns NotFoundException
- **WHEN** a session and run exist but no verdict has been saved
- **THEN** a NotFoundException SHALL be thrown

### Requirement: FinalizeSession integration test validates session freeze and snapshot
The system SHALL have a test file `tests/use-cases/finalize-session.integration.spec.ts`.

#### Scenario: Session finalized successfully
- **WHEN** a session with a completed run exists and `FinalizeSessionUseCase.execute()` is called
- **THEN** the session in the database SHALL have Frozen status, a frozenAt timestamp, and a snapshotUrl
- **AND** the verdict and citations SHALL be persisted in the database
- **AND** the mock SnapshotStore.upload SHALL have been called

### Requirement: CleanupExpiredSessions integration test validates cascading deletion
The system SHALL have a test file `tests/use-cases/cleanup-expired-sessions.integration.spec.ts`.

#### Scenario: Expired sessions cleaned up
- **WHEN** expired sessions exist in the database and `CleanupExpiredSessionsUseCase.execute()` is called
- **THEN** those sessions, their runs, verdicts, and citations SHALL be deleted from the database
- **AND** the mock SnapshotStore.delete SHALL have been called for each expired session's snapshot URL

#### Scenario: Active sessions are not cleaned up
- **WHEN** only active sessions exist
- **THEN** `execute()` SHALL return 0 and no sessions SHALL be deleted

### Requirement: StreamProgress integration test validates event generation
The system SHALL have a test file `tests/use-cases/stream-progress.integration.spec.ts`.

#### Scenario: Progress events streamed for valid session
- **WHEN** a session and run exist in the database and the mock StreamReader yields events
- **THEN** `StreamProgressUseCase.execute()` SHALL yield those events as an async generator

#### Scenario: Expired session rejected
- **WHEN** a session is in Expired status
- **THEN** a GoneException SHALL be thrown

### Requirement: GetObservations integration test validates observation retrieval
The system SHALL have a test file `tests/use-cases/get-observations.integration.spec.ts`.

#### Scenario: Observations retrieved
- **WHEN** a session and run exist in the database and the mock StreamReader returns observations
- **THEN** `GetObservationsUseCase.execute()` SHALL return those observations
