## ADDED Requirements

### Requirement: ClaimVerificationWorkflow implements three-phase DAG
The system SHALL define a Temporal workflow `ClaimVerificationWorkflow` that executes 11 agents across three phases: Phase 1 (sequential ingestion), Phase 2 (parallel fan-out), Phase 3 (sequential synthesis).

#### Scenario: Successful three-phase execution
- **WHEN** ClaimVerificationWorkflow is started with a valid claim
- **THEN** Phase 1 runs ingestion-agent, claim-detector, entity-extractor sequentially
- **AND** Phase 2 runs claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence, source-validator in parallel
- **AND** Phase 3 runs blindspot-detector, synthesizer sequentially
- **AND** the workflow completes with status `completed`

#### Scenario: Phase ordering is enforced
- **WHEN** the workflow executes
- **THEN** Phase 2 does not start until all Phase 1 activities complete
- **AND** Phase 3 does not start until all Phase 2 activities complete

### Requirement: Run status updates at phase boundaries
The system SHALL transition the run status at each phase boundary and publish the transition to the progress stream for SSE relay.

#### Scenario: Status transitions through phases
- **WHEN** Phase 1 starts, run status transitions from `pending` to `ingesting`
- **AND** when Phase 2 starts, run status transitions to `analyzing`
- **AND** when Phase 3 starts, run status transitions to `synthesizing`
- **AND** when the workflow completes, run status transitions to `completed`

#### Scenario: Status published to progress stream
- **WHEN** a run status transition occurs
- **THEN** a progress event is published to `progress:{runId}` with the new status

### Requirement: Check-worthiness gate can cancel the run
The system SHALL cancel the run if the claim-detector activity returns a check-worthiness score below 0.4. Phases 2 and 3 are skipped.

#### Scenario: Low check-worthiness cancels run
- **WHEN** claim-detector returns a score of 0.3
- **THEN** the run transitions to `cancelled`
- **AND** Phases 2 and 3 are not executed
- **AND** a workflow_completed signal is emitted with cancellation status

#### Scenario: Sufficient check-worthiness continues
- **WHEN** claim-detector returns a score of 0.7
- **THEN** Phase 2 proceeds normally

### Requirement: Workflow signals backend on completion or failure
The system SHALL emit a `workflow_completed` signal when all phases finish or the run is cancelled, and a `workflow_failed` signal when an unrecoverable failure occurs. The NestJS backend listens for these signals.

#### Scenario: Successful completion signal
- **WHEN** Phase 3 completes and the synthesizer emits a verdict
- **THEN** the workflow emits a `workflow_completed` signal with runId and final status

#### Scenario: Failure signal after retry exhaustion
- **WHEN** an activity fails after 3 retries
- **THEN** the workflow transitions the run to `failed`
- **AND** emits a `workflow_failed` signal with runId and error details

### Requirement: Workflow survives process crashes
The system SHALL leverage Temporal's durable execution to automatically resume workflow execution after a process crash, replaying from the event history without losing progress.

#### Scenario: Crash recovery mid-Phase-2
- **WHEN** the workflow process crashes during Phase 2 parallel execution
- **AND** the worker restarts
- **THEN** the workflow resumes from the last completed activity
- **AND** already-completed Phase 2 activities are not re-executed
