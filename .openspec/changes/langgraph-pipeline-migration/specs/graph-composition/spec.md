## ADDED Requirements

### Requirement: Pipeline graph connects nodes with correct edge topology
The system SHALL define a `ClaimVerificationPipeline` StateGraph in `pipeline/graph.py` with the following edge topology: intake -> fan_out_router -> [evidence, coverage] (parallel) -> fan_in -> validation -> synthesizer. The graph SHALL be compiled at module level.

#### Scenario: Linear path for check-worthy claim
- **WHEN** a check-worthy claim enters the pipeline with all API keys configured
- **THEN** execution follows: intake -> evidence + coverage (parallel) -> validation -> synthesizer

#### Scenario: Direct to synthesizer for not-check-worthy claim
- **WHEN** intake sets is_check_worthy=False
- **THEN** the fan_out_router returns `[Send("synthesizer", state)]`, skipping evidence, coverage, and validation

### Requirement: Fan-out dispatches evidence and coverage in parallel
The system SHALL implement a `fan_out_router` function that returns a list of `Send` objects for parallel execution. Evidence is always dispatched. Coverage is dispatched only when `has_newsapi_key()` returns True.

#### Scenario: Parallel evidence and coverage
- **WHEN** fan_out_router executes with is_check_worthy=True and NewsAPI key present
- **THEN** it returns `[Send("evidence", state), Send("coverage", state)]`

#### Scenario: Evidence only when no NewsAPI key
- **WHEN** fan_out_router executes with is_check_worthy=True and no NewsAPI key
- **THEN** it returns `[Send("evidence", state)]`

### Requirement: Fan-in merges parallel node outputs
The system SHALL merge state updates from parallel evidence and coverage nodes after both complete. Partial failures SHALL be handled: if one node fails, its state fields remain empty and the error is recorded in PipelineState.errors.

#### Scenario: Both nodes succeed
- **WHEN** evidence and coverage both complete successfully
- **THEN** PipelineState contains populated evidence and coverage fields

#### Scenario: Coverage fails, evidence succeeds
- **WHEN** evidence completes but coverage raises an exception
- **THEN** PipelineState contains evidence data, coverage fields are empty, and errors list contains the coverage failure message

### Requirement: Cancellation propagation
The system SHALL support cancellation via a Temporal signal. When the workflow receives a cancellation signal, it SHALL propagate to the LangGraph graph execution via an asyncio.Event, causing the current node to complete and the pipeline to exit cleanly.

#### Scenario: Cancellation during evidence node
- **WHEN** a cancellation signal arrives while evidence_node is executing
- **THEN** the pipeline stops after evidence_node completes its current operation, and the activity raises a CancelledError to Temporal
