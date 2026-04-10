## ADDED Requirements

### Requirement: Standardized activity input contract
The system SHALL define `AgentActivityInput` with fields: runId (string), claimText (string), sourceUrl (optional string), sourceDate (optional string), agentName (string), phase (enum: ingestion/fanout/synthesis). All 11 agent activities receive this same input type.

#### Scenario: Activity receives correct input
- **WHEN** the workflow dispatches an activity for coverage-left
- **THEN** the activity receives AgentActivityInput with agentName="coverage-left", phase="fanout"

#### Scenario: Optional fields are nullable
- **WHEN** a claim has no sourceUrl or sourceDate
- **THEN** the activity input has sourceUrl=None and sourceDate=None

### Requirement: Standardized activity output contract
The system SHALL define `AgentActivityOutput` with fields: agentName (string), terminalStatus (F or X), observationCount (int), durationMs (int). The workflow uses this output to determine phase completion and detect cancellations.

#### Scenario: Successful activity output
- **WHEN** an agent completes its session with 5 observations
- **THEN** the activity returns terminalStatus="F", observationCount=5

#### Scenario: Cancelled activity output
- **WHEN** an agent cancels its session (e.g., check-worthiness below threshold)
- **THEN** the activity returns terminalStatus="X", observationCount=0

### Requirement: Activity wraps agent session protocol
Each activity SHALL execute the agent session protocol: publish START message, run agent logic, publish STOP message. The activity is responsible for ensuring the START/STOP boundary is maintained even on failure.

#### Scenario: Normal activity execution
- **WHEN** an activity runs
- **THEN** a START message is published to `reasoning:{runId}:{agent}`
- **AND** the agent produces observations
- **AND** a STOP message is published with terminal status

#### Scenario: Activity failure still publishes STOP
- **WHEN** an agent encounters an error during processing
- **THEN** a STOP message is published with terminalStatus="X"
- **AND** the error is propagated to Temporal for retry handling

### Requirement: Retry policy handles transient LLM failures
Activities SHALL retry up to 3 times with exponential backoff (initial 5s, coefficient 2.0, max 30s) for transient errors including LLM rate limits, API timeouts, and network failures.

#### Scenario: Transient failure retried
- **WHEN** an activity fails with an HTTP 429 (rate limit) error
- **THEN** the activity is retried after 5 seconds
- **AND** if it fails again, retried after 10 seconds
- **AND** if it fails a third time, retried after 20 seconds

#### Scenario: Non-retryable failure fails immediately
- **WHEN** an activity fails with InvalidClaimError
- **THEN** the activity is not retried and fails immediately

### Requirement: Phase-specific activity timeouts
Phase 1 activities SHALL have a 30s start-to-close timeout. Phase 2 activities SHALL have a 45s timeout. Phase 3 activities SHALL have a 60s timeout. Schedule-to-close timeout is 2x the start-to-close timeout.

#### Scenario: Phase 1 timeout
- **WHEN** ingestion-agent does not complete within 30 seconds
- **THEN** the activity is timed out and eligible for retry

#### Scenario: Phase 3 extended timeout
- **WHEN** synthesizer is processing
- **THEN** it has 60 seconds to complete before timeout
