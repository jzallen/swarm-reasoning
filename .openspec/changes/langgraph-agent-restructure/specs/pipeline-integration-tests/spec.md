## ADDED Requirements

### Requirement: Per-node integration tests verify observation publishing to Redis
Each pipeline node (intake, evidence, coverage, validation, synthesizer) SHALL have an integration test that creates a real RedisReasoningStream and PipelineContext, executes the node with realistic input state, and reads observations back from Redis to verify correctness.

#### Scenario: Intake node publishes ingestion observations
- **WHEN** the intake node executes with a valid claim text and a real Redis connection
- **THEN** the Redis stream `reasoning:{run_id}:ingestion-agent` SHALL contain observations for CLAIM_TEXT, CLAIM_DOMAIN, CHECK_WORTHY_SCORE, CLAIM_NORMALIZED, and entity codes (ENTITY_PERSON, ENTITY_ORG, etc.) with status `F` and correct value types

#### Scenario: Evidence node publishes claimreview observations
- **WHEN** the evidence node executes with a normalized claim and mock API responses
- **THEN** the Redis stream `reasoning:{run_id}:claimreview-matcher` SHALL contain CLAIMREVIEW_MATCH, CLAIMREVIEW_VERDICT, CLAIMREVIEW_SOURCE observations with correct agent identity

#### Scenario: Coverage node publishes spectrum observations
- **WHEN** the coverage node executes with a claim and NewsAPI responses
- **THEN** Redis streams for coverage-left, coverage-center, and coverage-right agents SHALL each contain COVERAGE_ARTICLE_COUNT, COVERAGE_FRAMING, COVERAGE_TOP_SOURCE observations

#### Scenario: Validation node publishes source and blindspot observations
- **WHEN** the validation node executes with evidence and coverage state populated
- **THEN** the Redis stream for source-validator SHALL contain SOURCE_EXTRACTED_URL, SOURCE_VALIDATION_STATUS, SOURCE_CONVERGENCE_SCORE, CITATION_LIST observations and the blindspot-detector stream SHALL contain BLINDSPOT_SCORE, BLINDSPOT_DIRECTION

#### Scenario: Synthesizer node publishes verdict observations
- **WHEN** the synthesizer node executes with all upstream state populated
- **THEN** the Redis stream for synthesizer SHALL contain CONFIDENCE_SCORE, VERDICT, VERDICT_NARRATIVE observations with status `F`

### Requirement: Full-pipeline integration test verifies end-to-end state flow
The integration test suite SHALL include a test that invokes `pipeline_graph.ainvoke()` with a real PipelineContext and a check-worthy claim, verifying that all 5 nodes execute and produce correct final state.

#### Scenario: Check-worthy claim produces complete verdict
- **WHEN** the full pipeline executes with a check-worthy claim, real Redis, and mocked external APIs
- **THEN** the final PipelineState SHALL contain non-null values for verdict, confidence, and narrative, and Redis SHALL contain observation streams for all participating agents

#### Scenario: Not-check-worthy claim skips to synthesizer
- **WHEN** the full pipeline executes with a non-check-worthy claim (e.g., opinion statement)
- **THEN** the pipeline SHALL route directly from intake to synthesizer, skipping evidence/coverage/validation nodes, and the final state SHALL have is_check_worthy=False

### Requirement: Integration tests use isolated Redis keys
Each integration test SHALL use a unique run_id to create isolated Redis stream keys, preventing cross-test contamination when tests run in parallel or sequentially.

#### Scenario: Concurrent integration tests do not interfere
- **WHEN** two integration tests execute simultaneously with different run_ids
- **THEN** each test SHALL only observe its own observations in Redis streams, with zero cross-contamination

### Requirement: Integration tests are skippable without Docker
Integration tests SHALL be marked with `@pytest.mark.integration` and SHALL skip gracefully when Redis is unavailable, allowing unit tests to run without Docker Compose.

#### Scenario: Integration tests skip when Redis is down
- **WHEN** pytest runs with `-m integration` and Redis is not available on localhost:6379
- **THEN** all integration tests SHALL be skipped with a clear message, and zero tests SHALL fail due to connection errors
