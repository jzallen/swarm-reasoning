## Prerequisites

- [x] Slice 1 (types/stream) is complete: `swarm_reasoning.models`, `swarm_reasoning.stream.redis` are importable
- [x] Orchestrator core slice is complete: `run_agent_activity` Temporal activity is defined
- [x] Ingestion agent slice is complete: `reasoning:{runId}:ingestion-agent` streams are populated with `CLAIM_TEXT` observations
- [ ] `ANTHROPIC_API_KEY` env var is set in the dev environment

---

## 1. Package Scaffolding

- [x] 1.1 Create `services/agent-service/src/agents/claim_detector/__init__.py`
- [x] 1.2 Create `services/agent-service/src/agents/claim_detector/prompts.py` -- scoring prompt template as a module-level string constant `SCORING_PROMPT`
- [x] 1.3 Create `services/agent-service/src/agents/claim_detector/normalizer.py` -- `normalize_claim_text()` function and `NormalizeResult` dataclass
- [x] 1.4 Create `services/agent-service/src/agents/claim_detector/scorer.py` -- `score_claim_text()` function and `ScoreResult` dataclass; `CHECK_WORTHY_THRESHOLD = 0.4` constant
- [x] 1.5 Create `services/agent-service/src/agents/claim_detector/handler.py` -- `ClaimDetectorHandler` class wiring normalization + scoring + stream I/O
- [x] 1.6 Register `claim-detector` handler in the agent registry so `run_agent_activity` can look it up by name
- [x] 1.7 Verify `anthropic>=0.25` is in the agent-service `pyproject.toml` dependencies

---

## 2. Normalizer Implementation (`normalizer.py`)

- [x] 2.1 Implement Unicode-aware lowercasing via `str.casefold()`
- [x] 2.2 Implement hedging phrase removal using the regex lexicon defined in `specs/claim-normalization/spec.md Step 2`; compile patterns at module load (not per-call)
- [x] 2.3 Implement whitespace collapse and punctuation artifact cleanup (`, ,` -> `,`)
- [x] 2.4 Implement opportunistic pronoun resolution: single-person, single-org cases; skip on ambiguity
- [x] 2.5 Implement empty-output fallback: return `casefold(raw_text)` with `fallback_used = True`
- [x] 2.6 Implement 200-char truncation with word-boundary detection and `"..."` suffix
- [x] 2.7 Return `NormalizeResult` with `normalized`, `hedges_removed`, `pronouns_resolved`, `fallback_used`

---

## 3. Scorer Implementation (`scorer.py`)

- [x] 3.1 Implement `SCORING_PROMPT` construction in `prompts.py` -- inject normalized claim text, return JSON format instruction
- [x] 3.2 Implement `score_claim_text(normalized_text: str, client: AsyncAnthropic) -> ScoreResult` with structured JSON extraction
- [x] 3.3 Implement retry logic (up to 2 retries on malformed JSON) with `temperature = 0` on retries
- [x] 3.4 Implement score clamping to [0.0, 1.0]
- [x] 3.5 Implement self-consistency check: second Claude call "confirm or revise"; if `|pass1 - pass2| > 0.1` use `min(pass1, pass2)`
- [x] 3.6 Implement `CHECK_WORTHY_THRESHOLD = 0.4` constant and `is_check_worthy(score: float) -> bool`
- [x] 3.7 Return `ScoreResult` with `score`, `rationale`, `proceed`, `passes` (list of per-pass scores)

---

## 4. Agent Handler (`handler.py`)

- [x] 4.1 Implement `ClaimDetectorHandler.__init__` accepting `stream: ReasoningStream`, `anthropic_client: AsyncAnthropic`
- [x] 4.2 Implement `async def run(self, run_id: str) -> AgentResult`:
  - [x] 4.2.1 Publish `START` message to `reasoning:{run_id}:claim-detector`
  - [x] 4.2.2 Read `CLAIM_TEXT` from `reasoning:{run_id}:ingestion-agent` stream; raise `StreamNotFound` if absent
  - [x] 4.2.3 Read `ENTITY_PERSON` and `ENTITY_ORG` observations from ingestion stream (may be empty lists)
  - [x] 4.2.4 Call `normalize_claim_text()` and publish `CLAIM_NORMALIZED` observation (`seq=1`, `status=F`, `method="normalize_claim"`)
  - [x] 4.2.5 Publish progress event: `"Normalizing claim text..."`
  - [x] 4.2.6 Call `score_claim_text()` and publish `CHECK_WORTHY_SCORE` with `status=P` (pass 1 score)
  - [x] 4.2.7 Complete self-consistency check and publish `CHECK_WORTHY_SCORE` with `status=F` (final score)
  - [x] 4.2.8 Publish progress event: `"Check-worthiness score: {score} (threshold: 0.4)"`
  - [x] 4.2.9 Publish `STOP` message with `finalStatus = "F"` or `"X"` based on threshold
  - [x] 4.2.10 Publish progress event: gate decision message
  - [x] 4.2.11 Return `AgentResult` with `score`, `proceed`, `final_status`, `observation_count = 3`
- [x] 4.3 Implement Temporal activity heartbeating: call `activity.heartbeat()` every 10 seconds during LLM calls
- [x] 4.4 Classify errors: Anthropic rate limits/timeouts are retryable; auth errors and `StreamNotFound` are non-retryable

---

## 5. Progress Events

- [x] 5.1 Publish `"Normalizing claim text..."` at handler start
- [x] 5.2 Publish `"Scoring check-worthiness..."` before LLM call
- [x] 5.3 Publish `"Check-worthiness score: {score} (threshold: 0.4)"` after scoring
- [x] 5.4 Publish `"Claim is check-worthy, proceeding to analysis"` or `"Claim is not check-worthy (score {score} < 0.4), cancelling run"` after gate decision
- [x] 5.5 Write unit test verifying progress events are published in correct order

---

## 6. Unit Tests

- [x] 6.1 Create `tests/unit/agents/test_normalizer.py`:
  - [x] 6.1.1 All 12+ unit test scenarios from `specs/claim-normalization/spec.md Test Scenarios`
  - [x] 6.1.2 Parametrize hedge removal tests over the full lexicon (one test per phrase)
  - [x] 6.1.3 Test that `hedges_removed` list is populated correctly
  - [x] 6.1.4 Test that `normalize_claim_text` is a pure function (no I/O, no LLM calls)
- [x] 6.2 Create `tests/unit/agents/test_scorer.py`:
  - [x] 6.2.1 All 8 unit test scenarios from `specs/check-worthiness/spec.md Test Scenarios` using `AsyncMock` for Claude client
  - [x] 6.2.2 Test threshold boundary: `score=0.40` -> `proceed=True`; `score=0.39` -> `proceed=False`
  - [x] 6.2.3 Test malformed JSON response handling (mock Claude returning non-JSON)
  - [x] 6.2.4 Test score clamping (mock Claude returning `{"score": 1.5}`)
  - [x] 6.2.5 Test self-consistency: mock two divergent scores -> lower selected
- [x] 6.3 Create `tests/unit/agents/test_claim_detector_handler.py`:
  - [x] 6.3.1 Test happy path with mocked stream and Claude
  - [x] 6.3.2 Test below-threshold cancellation path
  - [x] 6.3.3 Test `StreamNotFound` when ingestion stream absent
  - [ ] 6.3.4 Test heartbeat calls during execution

---

## 7. Integration Tests

- [ ] 7.1 Create `tests/integration/agents/test_claim_detector.py`:
  - [ ] 7.1.1 Fixture: initialize Redis, populate ingestion stream with `CLAIM_TEXT = "Biden signed executive order 14042..."`
  - [ ] 7.1.2 Mock `AsyncAnthropic` client (avoid real LLM calls in CI)
  - [ ] 7.1.3 Test: handler publishes `CLAIM_NORMALIZED` (seq=1, status=F) before `CHECK_WORTHY_SCORE`
  - [ ] 7.1.4 Test: handler publishes `CHECK_WORTHY_SCORE` with P then F (seq=2, seq=3)
  - [ ] 7.1.5 Test: STOP message `observationCount = 3` and `finalStatus` matches threshold
  - [ ] 7.1.6 Test: below-threshold -> STOP `finalStatus = "X"`
  - [ ] 7.1.7 Test: handler raises `StreamNotFound` when ingestion stream absent
  - [ ] 7.1.8 Test: progress events appear in `progress:{runId}` stream in correct order
  - [ ] 7.1.9 Test: Temporal activity retry on transient Anthropic error -- first attempt fails, second succeeds

---

## 8. Acceptance Criteria (Gherkin)

- [ ] 8.1 Scenario "Check-worthy claim proceeds to ANALYZING" passes end-to-end (requires orchestrator slice)
- [ ] 8.2 Scenario "Below-threshold claim is cancelled" passes end-to-end (requires orchestrator slice)
- [ ] 8.3 Scenario "Claim detector publishes normalized claim text" passes with live agent + Redis:
  - [x] 8.3.1 F-status CLAIM_NORMALIZED observation present in stream
  - [x] 8.3.2 Value is all-lowercase
  - [x] 8.3.3 Value does not contain "reportedly" or "allegedly"
- [ ] 8.4 Scenario "Progress events published" -- verify progress stream contains scoring and gate messages

---

## Completion Definition

All tasks above are checked. Unit tests pass (`pytest tests/unit/agents/test_normalizer.py tests/unit/agents/test_scorer.py tests/unit/agents/test_claim_detector_handler.py`). Integration tests pass with mocked Claude and live Redis. The claim-detector runs as a Temporal activity within the shared agent-service container. No per-agent Dockerfile exists. The 3-observation stream shape (CLAIM_NORMALIZED F, CHECK_WORTHY_SCORE P, CHECK_WORTHY_SCORE F, STOP) is validated by integration test assertions. Progress events appear in `progress:{runId}` stream.
