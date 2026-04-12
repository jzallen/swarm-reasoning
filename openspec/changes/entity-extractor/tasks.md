## Prerequisites

- [x] Slice 1 (types/stream) is complete: `swarm_reasoning.models`, `swarm_reasoning.stream.redis` are importable
- [x] Orchestrator core slice is complete: `run_agent_activity` Temporal activity is defined
- [x] Claim-detector slice is complete: `reasoning:{runId}:claim-detector` streams contain `CLAIM_NORMALIZED` observations
- [ ] `ANTHROPIC_API_KEY` env var is set in the dev environment

---

## 1. Package Setup

- [x] 1.1 Create module directory `services/agent-service/src/agents/entity_extractor/` with `__init__.py`
- [x] 1.2 Create `handler.py`, `extractor.py`, `publisher.py` files
- [x] 1.3 Create test directory structure: `services/agent-service/tests/unit/agents/`, `services/agent-service/tests/integration/agents/`
- [x] 1.4 Verify `anthropic>=0.25`, `pydantic>=2.0` are in the agent-service `pyproject.toml` dependencies

---

## 2. Configuration

- [x] 2.1 Implement agent configuration in `handler.py`: `ANTHROPIC_API_KEY`, `REDIS_URL` (default `redis://localhost:6379`), `MODEL_ID` (default `claude-haiku-4-5`), `MAX_TOKENS` (default `512`)
- [x] 2.2 Validate `ANTHROPIC_API_KEY` is present; raise clear error if missing

---

## 3. LLM Entity Extraction

- [x] 3.1 Define `EntityExtractionResult` Pydantic model in `extractor.py` with five `list[str]` fields: `persons`, `organizations`, `dates`, `locations`, `statistics`
- [x] 3.2 Implement `extract_entities_llm(claim: str, client: AsyncAnthropic, model_id: str, max_tokens: int) -> EntityExtractionResult` using the Anthropic SDK with structured output (JSON mode) and compact grounding prompt
- [x] 3.3 Prompt must instruct: extract only entities explicitly stated in the claim, return empty lists for missing types, dates in YYYYMMDD or YYYYMMDD-YYYYMMDD where possible
- [x] 3.4 Implement `LLMUnavailableError` exception for Anthropic API failures
- [x] 3.5 Write unit tests in `tests/unit/agents/test_extractor.py`:
  - Mock Claude response with two persons -> verify `persons` list has two entries
  - Mock Claude response with empty result -> verify all lists are empty
  - Mock Claude API failure -> verify `LLMUnavailableError` is raised
  - Mock Claude response with mixed entity types -> verify correct assignment

---

## 4. Observation Publisher

- [x] 4.1 Implement `normalize_date(date_str: str) -> tuple[str, str | None]` in `publisher.py` that returns `(normalized_value, note)` -- note is `"date-not-normalized"` if the string cannot be parsed, `None` otherwise
- [x] 4.2 Implement `publish_entities(run_id: str, result: EntityExtractionResult, stream: ReasoningStream) -> int` that:
  - Publishes START message (`phase="ingestion"`, `agent="entity-extractor"`)
  - Iterates entities in order: PERSON -> ORG -> DATE -> LOCATION -> STATISTIC
  - For each entity, publishes one OBS with the correct `ObservationCode`, `valueType=ST`, `status=P`, and incrementing `seq`
  - For ENTITY_DATE, normalizes the value and sets `note` if not normalized
  - Publishes STOP message with `finalStatus="F"` and correct `observationCount`
  - Returns the total count of OBS messages published
- [x] 4.3 Implement `publish_error_stop(run_id: str, stream: ReasoningStream)` that publishes STOP with `finalStatus="X"` when called after a successful START but before completion
- [x] 4.4 Write unit tests in `tests/unit/agents/test_publisher.py`:
  - Two persons + one org -> verify 3 OBS messages published with seq 1, 2, 3
  - Empty result -> verify 0 OBS messages, STOP observationCount=0
  - Date normalization: year "2021" -> "20210101-20211231"
  - Date normalization: unparseable -> raw string + note
  - Error path: verify STOP X is published after START

---

## 5. Agent Handler (Temporal Activity Integration)

- [x] 5.1 Implement `EntityExtractorHandler` class in `handler.py` with `run(run_id: str) -> AgentResult` async method
- [x] 5.2 Handler `run()` method:
  - Read `CLAIM_NORMALIZED` from `reasoning:{run_id}:claim-detector` stream; raise `StreamNotFound` if absent
  - Call `extract_entities_llm()` with the normalized claim text
  - Call `publish_entities()` to write START/OBS/STOP to Redis stream
  - Return `AgentResult` with terminal status, observation count, and duration
- [x] 5.3 Implement error handling: on LLM failure after START, call `publish_error_stop` and re-raise
- [x] 5.4 Register `entity-extractor` handler in the agent registry so `run_agent_activity` can look it up by name
- [x] 5.5 Implement Temporal activity heartbeating: call `activity.heartbeat()` every 10 seconds during LLM calls
- [x] 5.6 Classify errors: Anthropic rate limits/timeouts are retryable; auth errors and missing streams are non-retryable
- [x] 5.7 Publish progress events to `progress:{runId}`:
  - `"Extracting named entities..."` at start
  - `"Found {n} entities: {summary}"` after extraction
  - `"Entity extraction complete"` at STOP

---

## 6. Unit Tests

- [x] 6.1 Create `tests/unit/agents/test_entity_extractor_handler.py`:
  - Test happy path with mocked stream and Claude
  - Test LLM failure path: verify error STOP is published
  - Test empty entities: verify START + STOP with observationCount=0
  - Test heartbeat calls during execution
  - Test `StreamNotFound` when claim-detector stream absent

---

## 7. Integration Tests

- [x] 7.1 Write `tests/integration/agents/test_entity_extractor.py`:
  - Full flow: invoke handler -> verify Redis stream `reasoning:{runId}:entity-extractor` contains START, N OBS, STOP in order
  - Verify STOP `observationCount` matches actual OBS count in stream
  - Verify all OBS `code` values are in `{ENTITY_PERSON, ENTITY_ORG, ENTITY_DATE, ENTITY_LOCATION, ENTITY_STATISTIC}`
  - Verify seq is monotonically increasing with no gaps
- [x] 7.2 Write integration test: claim with no entities -> START + 0 OBS + STOP with observationCount=0
- [ ] 7.3 Write integration test: two separate runs with same claim -> two independent streams (no cross-contamination)
- [x] 7.4 Write integration test: progress events appear in `progress:{runId}` stream
- [ ] 7.5 Write integration test: Temporal activity retry on transient Anthropic error -- first attempt fails, second succeeds

---

## 8. Acceptance Criteria

- [x] 8.1 Scenario: tool registered in agent registry and callable by `run_agent_activity`
- [x] 8.2 Scenario: tool rejects missing claim-detector stream with `StreamNotFound`
- [x] 8.3 Scenario: persons extracted from claim produce ENTITY_PERSON observations
- [x] 8.4 Scenario: organizations extracted produce ENTITY_ORG observations
- [x] 8.5 Scenario: no entities in claim produces START + STOP with observationCount=0
- [x] 8.6 Scenario: Claude API failure raises retryable error; Temporal retries the activity
- [x] 8.7 Scenario: multiple persons produce multiple observations with monotonic seq
- [x] 8.8 Scenario: empty entity type produces no observations for that type
- [x] 8.9 Scenario: ENTITY_DATE values normalized to YYYYMMDD format
- [x] 8.10 Scenario: unresolvable date published with "date-not-normalized" note
- [x] 8.11 Scenario: progress events published to `progress:{runId}`

---

## Completion Definition

All tasks above are checked. Unit tests pass. Integration tests pass with mocked Claude and live Redis. The entity-extractor runs as a Temporal activity within the shared agent-service container. No per-agent Dockerfile exists. The stream shape (START + N OBS + STOP) is validated by integration tests. Entity types are published in deterministic order (PERSON, ORG, DATE, LOCATION, STATISTIC). Progress events appear in `progress:{runId}` stream.
