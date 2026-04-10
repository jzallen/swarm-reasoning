## 1. Corpus Fixture Assembly

- [ ] 1.1 Create `docs/validation/` directory
- [ ] 1.2 Curate and commit `docs/validation/corpus.json` with exactly 50 PolitiFact claims distributed across all five ADR-0008 categories (10 per category; `CLAIMREVIEW_INDEXED` and `NOT_CLAIMREVIEW_INDEXED` mutually exclusive)
- [ ] 1.3 Verify each entry has required fields: `id`, `claim_text`, `ground_truth`, `categories`, `politifact_url`, `captured_date`, `speaker`, `domain`
- [ ] 1.4 Manually confirm the 10 `NOT_CLAIMREVIEW_INDEXED` claims return no match in the Google Fact Check Tools API at time of corpus assembly
- [ ] 1.5 Write `docs/validation/corpus-schema.json` (JSON Schema for corpus fixture validation at harness load time)

## 2. Harness Package Setup

- [ ] 2.1 Create `tests/validation/` directory with `__init__.py`
- [ ] 2.2 Create `tests/validation/conftest.py` with pytest fixtures: corpus loader, API client (wrapping `httpx`), Redis client for stream inspection
- [ ] 2.3 Add `pytest-asyncio`, `httpx`, and `jsonschema` to `pyproject.toml` dev dependencies

## 3. Accuracy Scorer

- [ ] 3.1 Implement `tests/validation/scorer.py`:
  - `VerdictTier` enum (TRUE=5, MOSTLY_TRUE=4, HALF_TRUE=3, MOSTLY_FALSE=2, FALSE=1, PANTS_FIRE=0, UNVERIFIABLE=-1)
  - `within_one_tier(system_verdict: str, ground_truth: str) -> bool`
  - `score_run(claim: dict, run_result: dict) -> ClaimResult` (includes alignment, distance, confidence_score, synthesis_signal_count, distinct_agents, latency_s)
- [ ] 3.2 Implement `tests/validation/reporter.py`:
  - `per_category_summary(results: list[ClaimResult], category: str) -> CategorySummary`
  - `overall_summary(results: list[ClaimResult]) -> OverallSummary` (NFR-019 MUST/PLAN/WISH thresholds)
  - `write_report(summary: OverallSummary, path: str)` — writes `docs/validation/report-{timestamp}.json`
- [ ] 3.3 Implement directional constraints:
  - `FALSE_PANTS_FIRE` category: assert no system verdict maps to TRUE or MOSTLY_TRUE
  - `TRUE_MOSTLY_TRUE` category: assert no system verdict maps to FALSE or PANTS_FIRE

## 4. Harness Runner

- [ ] 4.1 Implement `tests/validation/runner.py`:
  - `create_session() -> str` — POST to `/sessions`, return `session_id`
  - `submit_claim(session_id: str, claim: dict) -> str` — POST to `/sessions/{session_id}/claims`, return `session_id`
  - `poll_until_published(session_id: str, timeout_s: float = 150.0) -> SessionResult` — polls `GET /sessions/{session_id}` until `status == frozen` or timeout
  - `fetch_verdict(session_id: str) -> VerdictResult` — GET `/sessions/{session_id}/verdict` for the session
  - `fetch_observation_streams(session_id: str) -> dict[str, list]` — GET `/sessions/{session_id}/observations` or XRANGE all `reasoning:{runId}:*` streams from Redis
  - `count_distinct_agents(streams: dict) -> int` — count distinct agent fields across all OBS messages
- [ ] 4.2 Implement sequential claim submission with parallel poll loop:
  - Submit all 50 claims sequentially (one POST at a time)
  - Poll all active runs in parallel using `asyncio.gather`
  - Enforce per-run 150s poll timeout (allows for NFR-001's 120s + overhead)

## 5. Baseline Runner

- [ ] 5.1 Implement `tests/validation/baseline.py`:
  - `submit_baseline_claim(claim: dict) -> str` — POST to `/sessions/{session_id}/claims` with `baseline_mode: true` header or query param that instructs the orchestrator to run a stripped Temporal workflow with only the `claimreview-matcher` activity and `synthesizer` activity
  - Reuse `poll_until_published` from runner.py
- [ ] 5.2 Add `baseline_mode` support to the orchestrator's Temporal workflow configuration (runs a stripped workflow with only `claimreview-matcher` and `synthesizer` activities, skipping all other agents)
- [ ] 5.3 Implement `tests/validation/comparison.py`:
  - `compute_gap(swarm_results: list[ClaimResult], baseline_results: list[ClaimResult]) -> GapResult`
  - `nfr_020_assessment(gap: float) -> dict` — MUST/PLAN/WISH pass/fail
  - `corpus_drift_check(swarm_results: list[ClaimResult]) -> list[str]` — returns IDs of claims where CLAIMREVIEW_MATCH != FALSE

## 6. Gherkin Step Implementations

- [ ] 6.1 Create `tests/validation/steps/` directory with `__init__.py`
- [ ] 6.2 Implement step definitions for all 9 scenarios in `validation-baseline.feature` (harness exercises all 11 agents):
  - `test_true_mostly_true.py` — Scenario: System correctly identifies true claims
  - `test_false_pants_fire.py` — Scenario: System correctly identifies false claims
  - `test_half_true.py` — Scenario: System handles ambiguous claims without overclaiming
  - `test_claimreview_indexed.py` — Scenario: System matches ClaimReview verdicts for indexed claims
  - `test_not_indexed_verdicts.py` — Scenario: Swarm produces verdicts for claims not in ClaimReview
  - `test_baseline_comparison.py` — Scenario: Swarm outperforms single-agent baseline on non-indexed claims
  - `test_audit_log.py` — Scenario: Every published run has a queryable audit log via `/sessions/:id/observations`
  - `test_signal_count.py` — Scenario: No run reaches completed state with fewer than 5 synthesis signals
  - `test_blindspot_confidence.py` — Scenario: Blindspot detection correlates with lower confidence scores
  - `test_latency.py` — Scenario: Total run time for a single claim does not exceed 120 seconds

## 7. CI Integration

- [ ] 7.1 Add `validate` target to `Makefile`:
  ```makefile
  validate:
      docker compose -f docs/infrastructure/docker-compose.yml up -d
      sleep 10  # wait for stack health
      python -m pytest tests/validation/ -v --tb=short
      docker compose -f docs/infrastructure/docker-compose.yml down
  ```
- [ ] 7.2 Add CI workflow step that runs `make validate` and archives `docs/validation/report-*.json` as a build artifact
- [ ] 7.3 Ensure CI exits non-zero if NFR-019 MUST threshold (≥ 70%) or NFR-020 MUST threshold (≥ 20 pp) is not met

## 8. Validation Reporting

- [ ] 8.1 Implement human-readable stdout summary table (printed by scorer after every corpus run):
  ```
  Category               Claims  Correct  Rate    Status
  TRUE_MOSTLY_TRUE       10      8        80.0%   PASS
  FALSE_PANTS_FIRE       10      7        70.0%   PASS
  HALF_TRUE              10      6        60.0%   FAIL
  CLAIMREVIEW_INDEXED    10      9        90.0%   PASS
  NOT_CLAIMREVIEW_INDEXED 10     6        60.0%   PASS
  ─────────────────────────────────────────────────────
  Overall                50      36       72.0%   PASS (MUST)
  NFR-020 gap (non-indexed): +30 pp              PASS (PLAN)
  ```
- [ ] 8.2 Write `docs/validation/report-template.md` documenting the JSON report schema fields (not auto-generated — a reference for analysts reading the output)

## 9. Integration Tests for the Harness Itself

- [ ] 9.1 Write unit tests for `scorer.py`: within-one-tier edge cases (exact match, adjacent tier, two-tier miss, UNVERIFIABLE), six-tier ordering
- [ ] 9.2 Write unit tests for `comparison.py`: gap computation, NFR-020 thresholds, corpus drift detection
- [ ] 9.3 Write unit tests for corpus schema validation: valid corpus, missing fields, wrong category distribution
