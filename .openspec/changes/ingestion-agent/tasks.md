## Prerequisites

- [x] Slice 1 (types/stream) is complete: `swarm_reasoning.models`, `swarm_reasoning.stream.redis` are importable
- [x] Orchestrator core slice is complete: `run_agent_activity` Temporal activity is defined
- [x] `ANTHROPIC_API_KEY` env var is set in the dev environment

---

## 1. Package Setup

- [x] 1.1 Create module directory `services/agent-service/src/agents/ingestion_agent/` with `__init__.py`
- [x] 1.2 Create `services/agent-service/src/agents/ingestion_agent/tools/` with `__init__.py`
- [x] 1.3 Create test directory structure: `services/agent-service/tests/unit/agents/`, `services/agent-service/tests/integration/agents/`
- [x] 1.4 Verify `anthropic>=0.25`, `python-dateutil`, `pydantic>=2.0` are in the agent-service `pyproject.toml` dependencies

---

## 2. Configuration

- [x] 2.1 Implement agent configuration loading in `handler.py`: `ANTHROPIC_API_KEY`, `REDIS_URL` (default `redis://localhost:6379`)
- [x] 2.2 Validate `ANTHROPIC_API_KEY` is present at agent startup; raise clear error if missing

---

## 3. Validation Layer

- [x] 3.1 Implement `validate_claim_text(text: str) -> None` in `validation.py`: raises `ValidationError` with reason code for empty, too-short (<5), too-long (>500)
- [x] 3.2 Implement `validate_source_url(url: str) -> None`: regex check `^https?://[^\s]+\.[^\s]{2,}$`; raises `ValidationError` with `SOURCE_URL_INVALID_FORMAT`
- [x] 3.3 Implement `normalize_date(date_str: str) -> str` using `dateutil.parser.parse`; returns YYYYMMDD string; raises `ValidationError` with `SOURCE_DATE_UNPARSEABLE` on failure
- [x] 3.4 Implement `check_duplicate(redis_client, run_id: str, claim_text: str) -> bool` using `SETNX reasoning:dedup:{run_id}:{sha256}` with 86400s TTL via `SET ... EX ... NX`
- [x] 3.5 Write unit tests for all validators covering valid inputs, boundary conditions, and each rejection reason

---

## 4. claim-intake Tool

- [x] 4.1 Implement `IngestionResult` Pydantic model in `tools/claim_intake.py`: `accepted`, `run_id`, `rejection_reason`, `normalized_date`
- [x] 4.2 Implement `ingest_claim` async function: validate rules 1-6 in order, publish START, publish CLAIM_TEXT/CLAIM_SOURCE_URL/CLAIM_SOURCE_DATE observations using `ReasoningStream`
- [x] 4.3 Implement rejection path: publish START, then X-status CLAIM_TEXT observation, then STOP with `finalStatus=X`
- [x] 4.4 Implement success path: publish START, then three F-status observations, leave stream open for `classify_domain`
- [x] 4.5 Implement `StreamPublishError` exception for Redis connection failures
- [x] 4.6 Implement `StreamNotOpenError` for detecting double-START condition
- [x] 4.7 Publish progress event: `"Validating claim submission..."` at start, `"Claim accepted, classifying domain..."` on success, `"Claim rejected: {reason}"` on failure
- [x] 4.8 Write unit tests for `ingest_claim` using mocked `ReasoningStream` and Redis: happy path, each rejection reason, Redis failure

---

## 5. domain-classification Tool

- [x] 5.1 Implement `ClassificationResult` Pydantic model in `tools/domain_cls.py`: `run_id`, `domain` (Literal of 7 codes), `confidence` (HIGH/LOW), `attempt_count`
- [x] 5.2 Implement `DOMAIN_VOCABULARY` constant: `frozenset` of the 7 valid codes
- [x] 5.3 Implement `build_prompt(claim_text: str, retry: bool = False) -> list[dict]` returning Anthropic messages format
- [x] 5.4 Implement `call_claude(client, prompt) -> str`: calls `anthropic.messages.create` with `model="claude-sonnet-4-6"`, `max_tokens=10`, `temperature=0`; returns stripped uppercase text
- [x] 5.5 Implement `classify_domain` async function:
  - Check stream precondition (stream exists, has START, no STOP); raise `StreamStateError` if not satisfied
  - Attempt 1: call Claude, check vocabulary
  - Attempt 2 if needed: retry with clarification suffix
  - Fallback to OTHER on two failures
  - Publish P observation (on valid result), then F observation
  - Publish STOP with correct `observationCount`
- [x] 5.6 Implement `ClassificationServiceError` for Anthropic API failures (connection, rate limit, auth)
- [x] 5.7 Publish progress event: `"Domain classified: {domain}"` on success
- [x] 5.8 Write unit tests for `classify_domain` with mocked Anthropic client: first-attempt success, second-attempt success, two-failure fallback, each vocabulary code, API errors
- [x] 5.9 Write unit tests for `build_prompt`: verify system prompt contains all 7 codes, retry suffix presence

---

## 6. Agent Handler (Temporal Activity Integration)

- [x] 6.1 Implement `IngestionAgentHandler` class in `handler.py` with `run(run_id, claim_text, source_url, source_date)` async method
- [x] 6.2 Handler `run()` method: call `ingest_claim`, then `classify_domain` if accepted, return `AgentResult`
- [x] 6.3 Handler manages Anthropic client and Redis connection lifecycle
- [x] 6.4 Register `ingestion-agent` handler in the agent registry so `run_agent_activity` can look it up by name
- [x] 6.5 Implement Temporal activity heartbeating within handler: call `activity.heartbeat()` every 10 seconds during LLM calls
- [x] 6.6 Classify errors as retryable (Anthropic rate limits, Redis connection errors) vs non-retryable (validation errors, auth errors)
- [ ] 6.7 Write unit tests for handler: happy path, validation failure path, LLM error path, heartbeat calls

---

## 7. Integration Tests

- [x] 7.1 Write integration test: full happy-path flow -- `ingest_claim` then `classify_domain` produces START + 3 F-status observations + 2 CLAIM_DOMAIN observations (P then F) + STOP against live Redis
- [x] 7.2 Write integration test: rejection path -- invalid claim text produces START + X-status CLAIM_TEXT + STOP with `finalStatus=X`
- [x] 7.3 Write integration test: duplicate detection -- second call with same claim_text and run_id returns rejected with `DUPLICATE_CLAIM_IN_RUN`
- [x] 7.4 Write integration test: stream state guard -- `classify_domain` called without prior `ingest_claim` raises `StreamStateError`
- [ ] 7.5 Write integration test: `classify_domain` with mocked Anthropic API returning each vocabulary code -- verify correct CLAIM_DOMAIN value in stream
- [x] 7.6 Write integration test: `classify_domain` fallback -- mock returns invalid value twice -- verify OTHER published with fallback note and stream closed with `finalStatus=F`
- [x] 7.7 Write integration test: progress events -- verify `progress:{runId}` stream contains expected progress messages for happy path and rejection path
- [ ] 7.8 Write integration test: Temporal activity retry -- simulate Anthropic rate limit on first attempt, success on retry; verify activity completes successfully

---

## 8. Acceptance Criteria (Gherkin)

- [x] 8.1 Scenario "Valid claim with full metadata is accepted" passes end-to-end
- [x] 8.2 Scenario "Claim text too short is rejected" passes with STOP `finalStatus=X`
- [x] 8.3 Scenario "Duplicate claim in same run is rejected" passes with dedup key check
- [x] 8.4 Scenario "Invalid source URL format is rejected" passes
- [x] 8.5 Scenario "Unparseable source date is rejected" passes
- [x] 8.6 Scenario "Domain classification succeeds on first attempt" passes with P and F observations in stream
- [x] 8.7 Scenario "Domain classification falls back to OTHER" passes with fallback note
- [x] 8.8 Scenario "Progress events are published" -- verify `progress:{runId}` contains agent start/completion messages

---

## Completion Definition

All tasks above are checked. Unit tests pass. Integration tests pass with mocked Claude and live Redis. The ingestion agent runs as a Temporal activity within the shared agent-service container. No per-agent Dockerfile exists. The 6-observation stream shape (START + CLAIM_TEXT F + CLAIM_SOURCE_URL F + CLAIM_SOURCE_DATE F + CLAIM_DOMAIN P + CLAIM_DOMAIN F + STOP) is validated by integration tests. Progress events appear in `progress:{runId}` stream.
