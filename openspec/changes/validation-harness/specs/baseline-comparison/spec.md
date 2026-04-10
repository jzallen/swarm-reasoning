## ADDED Requirements

### Requirement: Single-agent baseline runs ClaimReview-only path on non-indexed claims

The baseline runner SHALL submit each of the 10 `NOT_CLAIMREVIEW_INDEXED` corpus claims to the system using a stripped invocation that activates only the `claimreview-matcher` agent and the `synthesizer`. The coverage agents (left/center/right), domain-evidence, blindspot-detector, entity-extractor, and claim-detector SHALL NOT be invoked in baseline mode. The synthesizer SHALL receive only ClaimReview signal (which for non-indexed claims will be absent) and emit a verdict from that signal alone.

The baseline runner is test-only code (`tests/validation/baseline.py`). It calls the same NestJS backend API endpoints (`/sessions/:id/claims`, `/sessions/:id/verdict`) and does not bypass any production layer. The baseline runs a stripped Temporal workflow with only the `claimreview-matcher` and `synthesizer` activities.

#### Scenario: Baseline run uses stripped agent set

- **GIVEN** a non-indexed corpus claim is submitted in baseline mode
- **WHEN** the run completes to completed state
- **THEN** the Redis streams for that run contain START/STOP messages from `claimreview-matcher` and `synthesizer` only
- **AND** no START messages appear for coverage-left, coverage-center, coverage-right, domain-evidence, or blindspot-detector

#### Scenario: Baseline run receives no ClaimReview match for non-indexed claims

- **GIVEN** a `NOT_CLAIMREVIEW_INDEXED` corpus claim is submitted in baseline mode
- **WHEN** the claimreview-matcher completes
- **THEN** `CLAIMREVIEW_MATCH` is FALSE for the run
- **AND** `CLAIMREVIEW_MATCH_SCORE` is absent or 0.0

#### Scenario: Baseline synthesizer produces low-confidence or UNVERIFIABLE verdict

- **GIVEN** a baseline run where CLAIMREVIEW_MATCH is FALSE and no other agents ran
- **WHEN** the synthesizer emits the verdict
- **THEN** SYNTHESIS_SIGNAL_COUNT is 0 or 1
- **AND** CONFIDENCE_SCORE is below 0.40
- **AND** VERDICT is UNVERIFIABLE or reflects insufficient evidence

### Requirement: Swarm versus baseline gap computation (NFR-020)

The harness SHALL compute the swarm correct alignment rate and the baseline correct alignment rate on the same 10 non-indexed claims. Both rates SHALL use the same within-one-tier alignment metric. The gap (swarm rate minus baseline rate) SHALL be compared to the NFR-020 thresholds: MUST ≥ 20 pp, PLAN ≥ 30 pp, WISH ≥ 40 pp. The `make validate` CI target SHALL exit non-zero if the MUST threshold is not met.

#### Scenario: Swarm 60%, baseline 30% passes NFR-020 MUST threshold

- **GIVEN** the swarm achieves 6/10 correct on non-indexed claims
- **AND** the baseline achieves 3/10 correct
- **WHEN** the NFR-020 gap is computed
- **THEN** the gap is 30 percentage points
- **AND** MUST threshold (≥ 20 pp) is PASS
- **AND** PLAN threshold (≥ 30 pp) is PASS
- **AND** WISH threshold (≥ 40 pp) is FAIL

#### Scenario: Swarm 50%, baseline 40% fails NFR-020 MUST threshold

- **GIVEN** the swarm achieves 5/10 correct on non-indexed claims
- **AND** the baseline achieves 4/10 correct
- **WHEN** the NFR-020 gap is computed
- **THEN** the gap is 10 percentage points
- **AND** MUST threshold (≥ 20 pp) is FAIL
- **AND** the CI target exits with code 1

#### Scenario: SYNTHESIS_SIGNAL_COUNT gap assertion

- **GIVEN** both swarm and baseline runs have completed for all 10 non-indexed claims
- **WHEN** mean SYNTHESIS_SIGNAL_COUNT is compared
- **THEN** the swarm mean exceeds the baseline mean by at least 5 signals
- **AND** if this assertion fails, it is reported as a separate finding without failing the CI exit code (informational only)

### Requirement: Baseline results included in accuracy report

The accuracy report SHALL include a `baseline_comparison` section containing: the 10 non-indexed claim IDs evaluated in baseline mode, per-claim baseline verdicts, baseline alignment rate, swarm alignment rate on the same claims, gap in percentage points, and NFR-020 assessment (MUST/PLAN/WISH pass/fail).

#### Scenario: Report baseline_comparison section is complete

- **GIVEN** the full harness run has completed including baseline comparison
- **WHEN** the accuracy report JSON is inspected
- **THEN** the `baseline_comparison` object exists
- **AND** it contains `baseline_alignment_rate`, `swarm_alignment_rate_non_indexed`, `gap_percentage_points`, and `nfr_020_assessment`
- **AND** `per_claim_baseline` is an array of 10 entries each with `claim_id`, `baseline_verdict`, `swarm_verdict`, and `ground_truth`

### Requirement: ClaimReview indexing assertion before baseline run

Before running baseline comparison, the harness SHALL assert that all 10 non-indexed corpus claims return `CLAIMREVIEW_MATCH == FALSE` in swarm mode. If any of the 10 claims return a ClaimReview match, the harness SHALL flag them as "corpus drift" in the report (because PolitiFact may have since been indexed) and exclude those claims from the NFR-020 calculation.

#### Scenario: All 10 non-indexed claims confirm no ClaimReview match

- **GIVEN** swarm runs have completed for all 10 `NOT_CLAIMREVIEW_INDEXED` corpus claims
- **WHEN** CLAIMREVIEW_MATCH observations are checked for each run
- **THEN** all 10 runs have `CLAIMREVIEW_MATCH = FALSE^No Match^FCK`
- **AND** the NFR-020 calculation proceeds using all 10 claims

#### Scenario: Corpus drift detected for one non-indexed claim

- **GIVEN** 9 of 10 non-indexed claims return CLAIMREVIEW_MATCH=FALSE
- **AND** 1 claim now returns CLAIMREVIEW_MATCH=TRUE (newly indexed by PolitiFact)
- **WHEN** the corpus drift check runs
- **THEN** the drifted claim is flagged as `corpus_drift` in the report
- **AND** NFR-020 calculation uses only the remaining 9 claims
- **AND** the harness prints a warning: "Corpus drift detected: 1 claim(s) now indexed in ClaimReview. Re-curate corpus."
- **AND** the CI target does NOT exit non-zero due to corpus drift alone
