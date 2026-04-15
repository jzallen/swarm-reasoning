## ADDED Requirements

### Requirement: SessionController endpoint tests with mocked use cases
The system SHALL have a test file `tests/controllers/session.controller.spec.ts` that tests SessionController with mocked CreateSessionUseCase and GetSessionUseCase.

#### Scenario: POST /sessions returns 201 with formatted session
- **WHEN** a POST request is sent to `/sessions`
- **THEN** the response status SHALL be 201
- **AND** the response body SHALL contain the session formatted by SessionPresenter

#### Scenario: GET /sessions/:id returns 200 with session
- **WHEN** a GET request is sent to `/sessions/:id` with a valid UUID
- **THEN** the response status SHALL be 200
- **AND** the response body SHALL contain the formatted session

#### Scenario: GET /sessions/:id returns 404 when use case throws NotFoundException
- **WHEN** GetSessionUseCase throws NotFoundException
- **THEN** the response status SHALL be 404

#### Scenario: Invalid UUID returns 400
- **WHEN** a GET request is sent to `/sessions/not-a-uuid`
- **THEN** the response status SHALL be 400

### Requirement: ClaimController endpoint tests with mocked use case
The system SHALL have a test file `tests/controllers/claim.controller.spec.ts` that tests ClaimController with mocked SubmitClaimUseCase.

#### Scenario: POST /sessions/:id/claims returns 202 with formatted session
- **WHEN** a POST request with valid claimText is sent
- **THEN** the response status SHALL be 202
- **AND** SubmitClaimUseCase SHALL have been called with the session ID and claim data

#### Scenario: Empty claimText returns 400
- **WHEN** a POST request is sent with empty claimText
- **THEN** the response status SHALL be 400 (ValidationPipe rejects it)

#### Scenario: Missing claimText returns 400
- **WHEN** a POST request is sent with no claimText field
- **THEN** the response status SHALL be 400

#### Scenario: Extra fields rejected with 400
- **WHEN** a POST request includes unknown fields alongside claimText
- **THEN** the response status SHALL be 400 (forbidNonWhitelisted)

#### Scenario: Use case NotFoundException returns 404
- **WHEN** SubmitClaimUseCase throws NotFoundException
- **THEN** the response status SHALL be 404

#### Scenario: Use case ConflictException returns 409
- **WHEN** SubmitClaimUseCase throws ConflictException
- **THEN** the response status SHALL be 409

#### Scenario: Use case UnprocessableEntityException returns 422
- **WHEN** SubmitClaimUseCase throws UnprocessableEntityException
- **THEN** the response status SHALL be 422

### Requirement: VerdictController endpoint tests with mocked use case
The system SHALL have a test file `tests/controllers/verdict.controller.spec.ts` that tests VerdictController with mocked GetVerdictUseCase.

#### Scenario: GET /sessions/:id/verdict returns 200 with formatted verdict
- **WHEN** GetVerdictUseCase returns a verdict with citations
- **THEN** the response status SHALL be 200
- **AND** the body SHALL be formatted by VerdictPresenter

#### Scenario: No verdict returns 404
- **WHEN** GetVerdictUseCase throws NotFoundException
- **THEN** the response status SHALL be 404

### Requirement: EventController endpoint tests with mocked use case
The system SHALL have a test file `tests/controllers/event.controller.spec.ts` that tests EventController SSE behavior with mocked StreamProgressUseCase.

#### Scenario: GET /sessions/:id/events sets SSE headers
- **WHEN** a GET request is sent to `/sessions/:id/events`
- **THEN** the response SHALL have Content-Type `text/event-stream`
- **AND** Cache-Control SHALL be `no-cache`

#### Scenario: Session not found returns 404
- **WHEN** StreamProgressUseCase throws NotFoundException
- **THEN** the response status SHALL be 404

### Requirement: HealthController endpoint tests
The system SHALL have a test file `tests/controllers/health.controller.spec.ts` that tests HealthController with mocked DataSource and service ports.

#### Scenario: All services healthy returns 200
- **WHEN** all service health checks pass
- **THEN** the response status SHALL be 200
- **AND** status SHALL be "healthy"

#### Scenario: Degraded service returns 503
- **WHEN** the DataSource query throws an error
- **THEN** the response status SHALL be 503
- **AND** status SHALL be "degraded"

### Requirement: ObservationController endpoint tests with mocked use case
The system SHALL have a test file `tests/controllers/observation.controller.spec.ts` that tests ObservationController with mocked GetObservationsUseCase.

#### Scenario: GET /sessions/:id/observations returns 200 with observation data
- **WHEN** GetObservationsUseCase returns an array of observations
- **THEN** the response status SHALL be 200
- **AND** the body SHALL contain the observation array

#### Scenario: Session not found returns 404
- **WHEN** GetObservationsUseCase throws NotFoundException
- **THEN** the response status SHALL be 404
