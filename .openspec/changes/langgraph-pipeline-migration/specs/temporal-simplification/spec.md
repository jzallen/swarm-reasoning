## ADDED Requirements

### Requirement: Simplified 4-activity Temporal workflow
The system SHALL rewrite `ClaimVerificationWorkflow` to use exactly 4 activities in sequence: validate_claim_input (5s timeout), run_langgraph_pipeline (180s timeout, 30s heartbeat), persist_verdict (10s timeout), notify_frontend (5s timeout). The workflow SHALL be approximately 30 lines of code.

#### Scenario: Successful claim verification
- **WHEN** a valid claim is submitted to the workflow
- **THEN** it validates input, runs the full pipeline, persists the verdict, and notifies the frontend

#### Scenario: Invalid claim input
- **WHEN** validate_claim_input raises InvalidClaimError
- **THEN** the workflow fails with a non-retryable error and does not execute the pipeline

### Requirement: run_langgraph_pipeline is a single Temporal activity
The system SHALL register `run_langgraph_pipeline` as a Temporal activity in `activities/run_pipeline.py`. The activity SHALL invoke the compiled LangGraph pipeline, pass a heartbeat callback via RunnableConfig, and return a PipelineResult constructed from the final PipelineState.

#### Scenario: Activity heartbeats during execution
- **WHEN** the pipeline is executing and a node starts processing
- **THEN** the activity heartbeats with detail `executing:{node_name}` at the node boundary

#### Scenario: Activity retry on transient failure
- **WHEN** the pipeline fails with a retryable error
- **THEN** Temporal retries the activity up to 2 times per the RetryPolicy

#### Scenario: Non-retryable errors skip retry
- **WHEN** the pipeline raises InvalidClaimError or NotCheckWorthyError
- **THEN** Temporal does not retry the activity

### Requirement: Worker registers single pipeline activity
The system SHALL update worker.py to register `run_langgraph_pipeline` as the primary activity instead of individual per-agent activities. A single task queue SHALL serve all pipeline executions.

#### Scenario: Worker starts with pipeline activity
- **WHEN** the agent-service worker starts
- **THEN** it registers run_langgraph_pipeline, validate_claim_input, persist_verdict, and notify_frontend as activities on a single task queue

### Requirement: NestJS backend compatible with simplified workflow
The system SHALL verify that the NestJS backend Temporal client starts the simplified workflow correctly and that session/verdict persistence works with the PipelineResult format.

#### Scenario: Backend starts simplified workflow
- **WHEN** the frontend submits a claim via the API
- **THEN** the NestJS backend starts ClaimVerificationWorkflow with ClaimInput and receives a PipelineResult
