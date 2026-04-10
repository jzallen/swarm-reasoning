## ADDED Requirements

### Requirement: Within-one-tier alignment scoring

The accuracy scorer SHALL implement within-one-tier alignment as the correctness metric. The six-tier PolitiFact scale SHALL be encoded as an ordered numeric sequence: TRUE=5, MOSTLY_TRUE=4, HALF_TRUE=3, MOSTLY_FALSE=2, FALSE=1, PANTS_FIRE=0. A system verdict SHALL be considered correct if the absolute difference between the system verdict tier and the ground truth tier is at most 1. The system verdict is derived from the VERDICT observation emitted by the synthesizer.

#### Scenario: Exact match is correct

- **GIVEN** a corpus entry with ground truth `HALF_TRUE`
- **AND** the system emits verdict `HALF_TRUE`
- **WHEN** the alignment score is computed
- **THEN** the alignment result is `correct` with distance 0

#### Scenario: Adjacent tier is correct

- **GIVEN** a corpus entry with ground truth `TRUE`
- **AND** the system emits verdict `MOSTLY_TRUE`
- **WHEN** the alignment score is computed
- **THEN** the alignment result is `correct` with distance 1

#### Scenario: Two-tier miss is incorrect

- **GIVEN** a corpus entry with ground truth `TRUE`
- **AND** the system emits verdict `HALF_TRUE`
- **WHEN** the alignment score is computed
- **THEN** the alignment result is `incorrect` with distance 2

#### Scenario: UNVERIFIABLE verdict is always incorrect

- **GIVEN** any corpus entry regardless of ground truth
- **AND** the system emits verdict `UNVERIFIABLE`
- **WHEN** the alignment score is computed
- **THEN** the alignment result is `incorrect`

### Requirement: Per-category accuracy breakdown

The scorer SHALL compute alignment rates for each of the five corpus categories independently. Each per-category report SHALL include: claim count, correct count, alignment rate (correct / count), mean CONFIDENCE_SCORE, and pass/fail assessment against the category-specific threshold from the Gherkin feature.

#### Scenario: TRUE_MOSTLY_TRUE category passes at 70%

- **GIVEN** 10 corpus claims in the `TRUE_MOSTLY_TRUE` category have been processed
- **WHEN** the per-category report is computed
- **THEN** the report records alignment rate as correct_count / 10
- **AND** if alignment rate >= 0.70, the category is marked PASS
- **AND** if alignment rate < 0.70, the category is marked FAIL

#### Scenario: FALSE_PANTS_FIRE category directional check

- **GIVEN** 10 corpus claims in the `FALSE_PANTS_FIRE` category have been processed
- **WHEN** the per-category report is computed
- **THEN** the scorer also asserts that no system verdict for this category maps to TRUE or MOSTLY_TRUE
- **AND** a violation of this directional constraint marks the category as FAIL regardless of alignment rate

#### Scenario: HALF_TRUE category signal count assertion

- **GIVEN** 10 corpus claims in the `HALF_TRUE` category have been processed
- **WHEN** the per-category report is computed
- **THEN** the report includes the minimum SYNTHESIS_SIGNAL_COUNT across all 10 runs
- **AND** if any run has SYNTHESIS_SIGNAL_COUNT <= 10, that run is flagged in the report

### Requirement: Overall NFR-019 threshold check

The scorer SHALL compute an overall alignment rate across all 50 claims and compare it to the NFR-019 thresholds. The scorer SHALL output a three-tier assessment: MUST (≥ 70%), PLAN (≥ 80%), WISH (≥ 90%). The `make validate` CI target SHALL exit with a non-zero exit code if the MUST threshold is not met.

#### Scenario: 35 correct out of 50 passes MUST threshold

- **GIVEN** 35 of 50 corpus claims result in correct alignment
- **WHEN** the overall NFR-019 assessment is computed
- **THEN** overall alignment rate is 0.70
- **AND** MUST threshold is PASS
- **AND** PLAN threshold is FAIL
- **AND** WISH threshold is FAIL

#### Scenario: 40 correct out of 50 passes MUST and PLAN thresholds

- **GIVEN** 40 of 50 corpus claims result in correct alignment
- **WHEN** the overall NFR-019 assessment is computed
- **THEN** overall alignment rate is 0.80
- **AND** MUST threshold is PASS
- **AND** PLAN threshold is PASS
- **AND** WISH threshold is FAIL

#### Scenario: CI exits non-zero when MUST threshold fails

- **GIVEN** fewer than 35 of 50 corpus claims result in correct alignment
- **WHEN** the `make validate` target runs to completion
- **THEN** the process exits with exit code 1
- **AND** the failure summary identifies which categories drove the miss

### Requirement: Accuracy report written to file

After each corpus run, the scorer SHALL write a structured JSON report to `docs/validation/report-{timestamp}.json`. The report SHALL include: run timestamp, corpus version, per-claim results, per-category summaries, overall alignment rate, NFR-019 assessment, NFR-020 assessment, and total wall-clock time.

#### Scenario: Report file is created after a corpus run

- **GIVEN** the full 50-claim corpus has been processed
- **WHEN** the scorer completes
- **THEN** a file matching `docs/validation/report-*.json` is created
- **AND** the file contains a valid JSON object with `overall_alignment_rate` and `nfr_019_assessment` fields

#### Scenario: Per-claim result includes run ID for audit lookup

- **WHEN** the per-claim results in the report are inspected
- **THEN** each entry includes `session_id` (the UUID from the NestJS backend), `claim_id`, `ground_truth`, `system_verdict`, `alignment`, and `confidence_score`
- **AND** the `session_id` can be used to query `GET /sessions/{session_id}/observations` for the full audit stream

### Requirement: Audit log coverage assertion (NFR-022)

The scorer SHALL assert that every completed run has observation streams in Redis containing observations from at least 8 distinct agents. Runs that fail this assertion SHALL be flagged in the report and excluded from the accuracy calculation with a note.

#### Scenario: Run with 10 distinct agent streams passes audit check

- **GIVEN** a published run where all 11 agents emitted at least one OBS message
- **WHEN** the audit log coverage assertion is evaluated
- **THEN** the run passes with distinct_agents = 11

#### Scenario: Run with fewer than 8 distinct agent streams is flagged

- **GIVEN** a published run where only 6 distinct agents are represented in Redis
- **WHEN** the audit log coverage assertion is evaluated
- **THEN** the run is flagged as `audit_coverage_fail` in the report
- **AND** the run is excluded from the accuracy calculation
- **AND** the CI exit code reflects this exclusion

### Requirement: Run latency assertion (NFR-001)

The scorer SHALL record the elapsed time from POST `/sessions/{session_id}/claims` submission to session `frozen` status for each corpus claim. Any run exceeding 120 seconds SHALL be flagged in the report. The scorer SHALL also record the fan-out phase duration (from the first fan-out agent START message to the last fan-out agent STOP message).

#### Scenario: Run completing in 90 seconds is within all thresholds

- **GIVEN** a run completes in 90 seconds
- **WHEN** the latency assertion is evaluated
- **THEN** the run is marked MUST=PASS (≤ 120s), PLAN=PASS (≤ 90s), WISH=FAIL (> 60s)

#### Scenario: Run exceeding 120 seconds is flagged

- **GIVEN** a run takes 135 seconds to reach completed
- **WHEN** the latency assertion is evaluated
- **THEN** the run is marked MUST=FAIL
- **AND** the run is included in the accuracy calculation (latency is measured independently of verdict correctness)
