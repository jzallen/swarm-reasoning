## ADDED Requirements

### Requirement: Workflow uses 4-activity pattern
The ClaimVerificationWorkflow SHALL execute four activities in sequence: validate_input → run_langgraph_pipeline → persist_verdict → notify_frontend. Each activity SHALL be independently retryable with its own timeout configuration.

#### Scenario: Successful claim verification executes all 4 activities
- **WHEN** a valid claim is submitted to the workflow
- **THEN** the workflow SHALL execute validate_input, then run_langgraph_pipeline, then persist_verdict, then notify_frontend in strict sequence, and return a WorkflowResult with the verdict

#### Scenario: Pipeline failure does not execute persist or notify
- **WHEN** run_langgraph_pipeline raises a non-retryable ApplicationError
- **THEN** the workflow SHALL NOT execute persist_verdict or notify_frontend, and SHALL transition the run to FAILED status via the fail_run activity

### Requirement: validate_input activity validates claim before pipeline execution
The validate_input activity SHALL validate the claim text (non-empty, within length limits) and session_id (valid format) before the pipeline executes. Invalid input SHALL raise a non-retryable ApplicationError.

#### Scenario: Empty claim text is rejected
- **WHEN** validate_input receives an empty claim_text
- **THEN** it SHALL raise ApplicationError with type "InvalidClaimError" and non_retryable=True

#### Scenario: Valid claim passes validation
- **WHEN** validate_input receives a non-empty claim_text and valid session_id
- **THEN** it SHALL return successfully, allowing the workflow to proceed to run_langgraph_pipeline

### Requirement: persist_verdict activity stores pipeline results
The persist_verdict activity SHALL take PipelineResult and session_id, and persist the verdict, confidence score, narrative, and observation count to the run status store.

#### Scenario: Verdict is persisted after successful pipeline run
- **WHEN** persist_verdict receives a PipelineResult with verdict="mostly-true" and confidence=0.78
- **THEN** the run status store SHALL contain the verdict, confidence, narrative, and the run status SHALL transition to COMPLETED

#### Scenario: persist_verdict is retryable on transient failure
- **WHEN** persist_verdict fails due to a transient database error
- **THEN** the Temporal retry policy SHALL retry the activity up to 3 times with exponential backoff

### Requirement: notify_frontend activity publishes verdict-ready event
The notify_frontend activity SHALL publish a VERDICT_READY event to the Redis progress stream (`progress:{run_id}`) for SSE relay to the frontend.

#### Scenario: Frontend receives verdict notification via SSE
- **WHEN** notify_frontend executes after persist_verdict completes
- **THEN** the progress stream SHALL contain a message with type "VERDICT_READY", the session_id, and the verdict summary

#### Scenario: notify_frontend failure does not fail the workflow
- **WHEN** notify_frontend fails (e.g., Redis unavailable)
- **THEN** the workflow SHALL log the error but return successfully, since the verdict is already persisted

### Requirement: Worker registers all 4 activities
The Temporal worker SHALL register validate_input, run_langgraph_pipeline, persist_verdict, and notify_frontend activities alongside the existing run_status activities.

#### Scenario: Worker starts with all activities registered
- **WHEN** the worker process starts
- **THEN** it SHALL register all pipeline activities and run_status activities on the "agent-task-queue" task queue
