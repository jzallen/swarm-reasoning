# Functional Requirements

**Extracted from:** Gherkin feature files in `docs/features/`

Each requirement has a unique ID (FR-NNN), acceptance criteria, and source traceability to the original feature scenario.

## Agent Output Contracts

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [FR-001](FR-agent-output-contracts.md#fr-001-ingestion-agent-required-observations) | Ingestion Agent Required Observations | Must | Accepted |
| [FR-002](FR-agent-output-contracts.md#fr-002-ingestion-agent-attribution) | Ingestion Agent Attribution | Must | Accepted |
| [FR-003](FR-agent-output-contracts.md#fr-003-special-character-handling-in-claim-text) | Special Character Handling in Claim Text | Must | Accepted |
| [FR-004](FR-agent-output-contracts.md#fr-004-claim-detector-normalized-output) | Claim Detector Normalized Output | Must | Accepted |
| [FR-005](FR-agent-output-contracts.md#fr-005-entity-extractor-per-entity-output) | Entity Extractor Per-Entity Output | Must | Accepted |
| [FR-006](FR-agent-output-contracts.md#fr-006-entity-extractor-no-statistic-case) | Entity Extractor No-Statistic Case | Must | Accepted |
| [FR-007](FR-agent-output-contracts.md#fr-007-coverage-agent-stream-output) | Coverage Agent Stream Output | Must | Accepted |

## Observation Resolution

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [FR-008](FR-observation-resolution.md#fr-008-c-status-resolution) | C-Status Resolution | Must | Accepted |
| [FR-009](FR-observation-resolution.md#fr-009-f-status-resolution) | F-Status Resolution | Must | Accepted |
| [FR-010](FR-observation-resolution.md#fr-010-x-status-exclusion) | X-Status Exclusion | Must | Accepted |
| [FR-011](FR-observation-resolution.md#fr-011-p-status-exclusion) | P-Status Exclusion | Must | Accepted |

## Confidence Score Computation and Verdict Mapping

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [FR-012](FR-confidence-and-verdict.md#fr-012-full-evidence-confidence-calibration) | Full Evidence Confidence Calibration | Must | Accepted |
| [FR-013](FR-confidence-and-verdict.md#fr-013-missing-claimreview-confidence-penalty) | Missing ClaimReview Confidence Penalty | Must | Accepted |
| [FR-014](FR-confidence-and-verdict.md#fr-014-blindspot-score-confidence-penalty) | Blindspot Score Confidence Penalty | Must | Accepted |
| [FR-015](FR-confidence-and-verdict.md#fr-015-unverifiable-verdict-on-low-signal-count) | Unverifiable Verdict on Low Signal Count | Must | Accepted |
| [FR-016](FR-confidence-and-verdict.md#fr-016-confidence-to-verdict-mapping) | Confidence-to-Verdict Mapping | Must | Accepted |
| [FR-017](FR-confidence-and-verdict.md#fr-017-claimreview-agreement--no-override) | ClaimReview Agreement — No Override | Must | Accepted |
| [FR-018](FR-confidence-and-verdict.md#fr-018-claimreview-disagreement--override-recorded) | ClaimReview Disagreement — Override Recorded | Must | Accepted |

## Orchestration Rules

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [FR-019](FR-orchestration-rules.md#fr-019-no-subagent-to-subagent-dispatch) | No Subagent-to-Subagent Dispatch | Must | Accepted |
| [FR-020](FR-orchestration-rules.md#fr-020-orchestrator-manages-all-agent-task-queues) | Orchestrator Manages All Agent Task Queues | Must | Accepted |
| [FR-021](FR-orchestration-rules.md#fr-021-entity-extraction-triggers-phase-2-fan-out) | Entity Extraction Triggers Phase 2 Fan-out | Must | Accepted |
| [FR-022](FR-orchestration-rules.md#fr-022-completion-on-stop-receipt-not-activity-return) | Completion on STOP Receipt, Not Activity Return | Must | Accepted |
| [FR-023](FR-orchestration-rules.md#fr-023-blindspot-detector-gate) | Blindspot Detector Gate | Must | Accepted |
| [FR-024](FR-orchestration-rules.md#fr-024-synthesizer-gate) | Synthesizer Gate | Must | Accepted |
| [FR-025](FR-orchestration-rules.md#fr-025-agent-get_observations-activity) | Agent get_observations Activity | Must | Accepted |
| [FR-026](FR-orchestration-rules.md#fr-026-agent-get_terminal_status-activity) | Agent get_terminal_status Activity | Must | Accepted |
| [FR-027](FR-orchestration-rules.md#fr-027-pull-pattern--blindspot-detector-data-request) | Pull Pattern — Blindspot Detector Data Request | Must | Accepted |
| [FR-028](FR-orchestration-rules.md#fr-028-pull-pattern--synthesizer-full-observation-log) | Pull Pattern — Synthesizer Full Observation Log | Must | Accepted |
| [FR-029](FR-orchestration-rules.md#fr-029-unacknowledged-entry-recovery) | Unacknowledged Entry Recovery | Must | Accepted |
| [FR-030](FR-orchestration-rules.md#fr-030-completion-state-reconstruction-after-restart) | Completion State Reconstruction After Restart | Must | Accepted |

## Verdict Publication and Schema Validation

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [FR-031](FR-publication-schema.md#fr-031-publication-trigger-on-synthesizer-stop) | Publication Trigger on Synthesizer STOP | Must | Accepted |
| [FR-032](FR-publication-schema.md#fr-032-no-publication-on-preliminary-verdict) | No Publication on Preliminary Verdict | Must | Accepted |
| [FR-033](FR-publication-schema.md#fr-033-correction-resolution-during-publication) | Correction Resolution During Publication | Must | Accepted |
| [FR-034](FR-publication-schema.md#fr-034-x-status-exclusion-during-publication) | X-Status Exclusion During Publication | Must | Accepted |
| [FR-035](FR-publication-schema.md#fr-035-required-verdict-json-fields) | Required Verdict JSON Fields | Must | Accepted |
| [FR-036](FR-publication-schema.md#fr-036-coverage-field-structure) | Coverage Field Structure | Must | Accepted |
| [FR-037](FR-publication-schema.md#fr-037-successful-schema-validation) | Successful Schema Validation | Must | Accepted |
| [FR-038](FR-publication-schema.md#fr-038-verdict-controlled-vocabulary-validation) | Verdict Controlled Vocabulary Validation | Must | Accepted |
| [FR-039](FR-publication-schema.md#fr-039-confidence-score-range-validation) | Confidence Score Range Validation | Must | Accepted |
| [FR-040](FR-publication-schema.md#fr-040-no-automatic-retry-on-validation-failure) | No Automatic Retry on Validation Failure | Must | Accepted |
| [FR-041](FR-publication-schema.md#fr-041-verdict-queryable-via-session-endpoint) | Verdict Queryable via Session Endpoint | Must | Accepted |
