## ADDED Requirements

### Requirement: Session creation returns UUID and active status
The system SHALL create a new session via POST /sessions and return a Session object with a UUID v4 sessionId, status `active`, and createdAt timestamp.

#### Scenario: Successful session creation
- **WHEN** POST /sessions is called
- **THEN** a 201 response is returned with a Session object
- **AND** sessionId is a valid UUID v4
- **AND** status is `active`
- **AND** createdAt is a UTC ISO 8601 timestamp

#### Scenario: Service unavailable
- **WHEN** POST /sessions is called and PostgreSQL is unreachable
- **THEN** a 503 response is returned with an ErrorResponse

### Requirement: Session status follows active -> frozen -> expired lifecycle
The system SHALL enforce that sessions transition only forward through the lifecycle: active -> frozen -> expired. Backwards transitions SHALL be rejected.

#### Scenario: Session freezes on verdict finalization
- **WHEN** FinalizeSessionUseCase processes a completed run
- **THEN** the session status transitions from `active` to `frozen`
- **AND** frozenAt is set to the current UTC timestamp
- **AND** expiresAt is set to frozenAt + 3 days

#### Scenario: Frozen session cannot revert to active
- **WHEN** an attempt is made to transition a frozen session to active
- **THEN** an InvalidStateTransition error is raised

#### Scenario: Expired session cleanup
- **WHEN** CleanupExpiredSessionsUseCase runs
- **AND** a session has expiresAt < now()
- **THEN** the session and all associated data (run, verdict, citations, S3 snapshot) are deleted

### Requirement: GET /sessions/:sessionId returns session with contextual data
The system SHALL return session data via GET /sessions/:sessionId. Active sessions include the claim and run status. Frozen sessions include the snapshotUrl.

#### Scenario: Active session with running claim
- **WHEN** GET /sessions/:sessionId is called for an active session
- **THEN** the response includes sessionId, status `active`, claim text, and createdAt

#### Scenario: Frozen session with snapshot URL
- **WHEN** GET /sessions/:sessionId is called for a frozen session
- **THEN** the response includes snapshotUrl pointing to the static HTML snapshot

#### Scenario: Session not found
- **WHEN** GET /sessions/:sessionId is called with a non-existent ID
- **THEN** a 404 response is returned with an ErrorResponse

### Requirement: Static HTML snapshot rendered on freeze
The system SHALL render a self-contained HTML page containing the verdict, citations, and chat history when a session transitions to frozen. The snapshot SHALL be uploaded to S3 and the URL stored on the session.

#### Scenario: Snapshot contains verdict and citations
- **WHEN** a session is frozen
- **THEN** StaticHtmlRenderer produces an HTML page with verdict rating, factuality score, narrative, and all citations

#### Scenario: Snapshot URL is accessible
- **WHEN** a session is frozen and the snapshot is uploaded
- **THEN** the snapshotUrl returns the static HTML page via HTTP GET
