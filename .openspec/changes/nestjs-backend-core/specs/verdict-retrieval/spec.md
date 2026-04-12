## ADDED Requirements

### Requirement: Verdict retrieval returns score, rating, narrative, and citations
The system SHALL return the finalized verdict via GET /sessions/:sessionId/verdict with factualityScore (0.0-1.0), ratingLabel (6-point scale), narrative, signalCount, citations array, and finalizedAt timestamp.

#### Scenario: Completed session returns full verdict
- **WHEN** GET /sessions/:sessionId/verdict is called for a session with a completed run
- **THEN** a 200 response is returned with the Verdict object
- **AND** factualityScore is between 0.0 and 1.0
- **AND** ratingLabel is one of: true, mostly-true, half-true, mostly-false, false, pants-on-fire
- **AND** citations is a non-empty array

#### Scenario: No verdict yet
- **WHEN** GET /sessions/:sessionId/verdict is called for a session with an active (not yet completed) run
- **THEN** a 404 response is returned with message indicating the verdict is not yet available

#### Scenario: Session not found
- **WHEN** GET /sessions/:sessionId/verdict is called with a non-existent sessionId
- **THEN** a 404 response is returned

### Requirement: Citations include validation status and convergence
Each citation in the verdict response SHALL include sourceUrl, sourceName, agent (which agent produced it), observationCode, validationStatus (live/dead/redirect/soft-404/timeout/not-validated), and convergenceCount (how many agents referenced this source).

#### Scenario: Citation with validated source
- **WHEN** a verdict is retrieved
- **THEN** each citation includes validationStatus from source-validator
- **AND** convergenceCount reflects the number of agents that independently cited the same source

#### Scenario: Citation with unvalidated source
- **WHEN** a citation's source was not checked by source-validator
- **THEN** validationStatus is `not-validated`

### Requirement: Observation audit log retrieval
The system SHALL return the full observation log for a session's run via GET /sessions/:sessionId/observations. Observations are read from all agent Redis Streams for the run.

#### Scenario: Full observation log returned
- **WHEN** GET /sessions/:sessionId/observations is called for a completed session
- **THEN** a 200 response is returned with an array of all observations from all 11 agents
- **AND** observations are ordered by timestamp

#### Scenario: Observations include epistemic status
- **WHEN** the observation log is retrieved
- **THEN** each observation includes the status field (P, F, C, or X)

#### Scenario: Session not found
- **WHEN** GET /sessions/:sessionId/observations is called with a non-existent sessionId
- **THEN** a 404 response is returned

### Requirement: Health check aggregates dependent service status
The system SHALL expose GET /health returning the health of PostgreSQL, Redis, and Temporal. Overall status is `healthy` if all are reachable, `degraded` if some are reachable, `unhealthy` if critical services (PostgreSQL) are unreachable.

#### Scenario: All services healthy
- **WHEN** GET /health is called and all services are reachable
- **THEN** status is `healthy` and all service statuses are `reachable`

#### Scenario: Redis unreachable
- **WHEN** GET /health is called and Redis is unreachable
- **THEN** status is `degraded` and redis is `unreachable`

#### Scenario: PostgreSQL unreachable
- **WHEN** GET /health is called and PostgreSQL is unreachable
- **THEN** status is `unhealthy` and postgresql is `unreachable`
