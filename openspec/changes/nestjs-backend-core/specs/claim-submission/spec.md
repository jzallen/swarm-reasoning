## ADDED Requirements

### Requirement: Claim submission validates input and starts workflow
The system SHALL accept a claim via POST /sessions/:sessionId/claims, validate the input, create a Run, start a Temporal ClaimVerificationWorkflow, and return 202 Accepted with the updated session.

#### Scenario: Valid claim submission
- **WHEN** POST /sessions/:sessionId/claims is called with valid claimText
- **THEN** a 202 response is returned
- **AND** a Run is created with status `pending`
- **AND** a Temporal ClaimVerificationWorkflow is started with the runId and claim data
- **AND** the session response includes the claim text

#### Scenario: Claim text exceeds max length
- **WHEN** POST /sessions/:sessionId/claims is called with claimText longer than 2000 characters
- **THEN** a 422 response is returned with a validation error

#### Scenario: Empty claim text rejected
- **WHEN** POST /sessions/:sessionId/claims is called with empty claimText
- **THEN** a 422 response is returned with a validation error

#### Scenario: Session not found
- **WHEN** POST /sessions/:sessionId/claims is called with a non-existent sessionId
- **THEN** a 404 response is returned

#### Scenario: Frozen session rejects claim
- **WHEN** POST /sessions/:sessionId/claims is called on a frozen session
- **THEN** a 422 response is returned with message indicating the session is no longer active

### Requirement: Claim includes optional source metadata
The system SHALL accept optional sourceUrl (valid URI) and sourceDate (ISO date) fields on claim submission. These are stored with the claim and passed to the agent pipeline.

#### Scenario: Claim with source URL and date
- **WHEN** a claim is submitted with sourceUrl and sourceDate
- **THEN** both fields are persisted and available in the session response

#### Scenario: Claim without optional fields
- **WHEN** a claim is submitted with only claimText
- **THEN** the claim is accepted and sourceUrl and sourceDate are null

### Requirement: SSE progress streaming for active runs
The system SHALL provide real-time progress updates via GET /sessions/:sessionId/events as a Server-Sent Events stream. Events are relayed from the Redis `progress:{runId}` stream.

#### Scenario: Progress events stream during analysis
- **WHEN** GET /sessions/:sessionId/events is called for a session with an active run
- **THEN** an SSE connection is opened
- **AND** events with type `progress` are emitted as agents complete work

#### Scenario: Verdict event closes stream
- **WHEN** the synthesizer completes and a verdict event is published
- **THEN** an event with type `verdict` is emitted
- **AND** a `close` event is emitted
- **AND** the SSE connection is closed

#### Scenario: No active run
- **WHEN** GET /sessions/:sessionId/events is called for a session with no active run
- **THEN** a `close` event is emitted immediately
