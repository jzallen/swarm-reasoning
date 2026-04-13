---
id: FR-confidence-and-verdict
title: "Confidence Score Computation and Verdict Mapping"
status: accepted
category: functional
priority: must
components: [synthesizer]
date: 2026-04-13
---

# Confidence Score Computation and Verdict Mapping

Functional requirements governing how the synthesizer computes confidence scores from resolved observations, maps scores to PolitiFact-equivalent verdicts, and handles ClaimReview agreement or override.

---

## FR-012: Full Evidence Confidence Calibration

**Description:** When the synthesizer receives a complete set of resolved evidence signals — including ClaimReview match, domain evidence alignment, cross-spectrum corroboration, and blindspot score — the computed confidence score must fall within a calibrated range that reflects the evidence balance.

**Acceptance Criteria:**

- Given resolved inputs including `CLAIMREVIEW_MATCH = TRUE`, `CLAIMREVIEW_VERDICT = FALSE`, `DOMAIN_EVIDENCE_ALIGNMENT = CONTRADICTS`, `CROSS_SPECTRUM_CORROBORATION = TRUE`, and `BLINDSPOT_SCORE = 0.12`, `CONFIDENCE_SCORE` is between 0.25 and 0.44
- The corresponding `VERDICT` is `MOSTLY_FALSE`

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "Full evidence set produces a well-calibrated confidence score"

---

## FR-013: Missing ClaimReview Confidence Penalty

**Description:** When no ClaimReview match exists for a claim, the synthesizer must produce a lower confidence score than it would with an equivalent evidence set that includes a ClaimReview match. This reflects the reduced evidentiary basis.

**Acceptance Criteria:**

- Given `CLAIMREVIEW_MATCH = FALSE` with otherwise identical evidence signals, `CONFIDENCE_SCORE` is lower than the equivalent scenario with `CLAIMREVIEW_MATCH = TRUE`

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "Missing ClaimReview match reduces confidence score"

---

## FR-014: Blindspot Score Confidence Penalty

**Description:** A high blindspot score (indicating significant coverage gaps across agents) must penalize the confidence score and be cited in the verdict narrative as a confidence-reducing factor.

**Acceptance Criteria:**

- Given `BLINDSPOT_SCORE = 0.90`, `CONFIDENCE_SCORE` is reduced by the blindspot penalty
- `VERDICT_NARRATIVE` references the blindspot as a confidence-reducing factor

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "High blindspot score penalizes confidence score"

---

## FR-015: Unverifiable Verdict on Low Signal Count

**Description:** When the synthesis signal count falls below a minimum threshold, the synthesizer must emit an `UNVERIFIABLE` verdict instead of attempting a scored verdict. No confidence score is emitted in this case.

**Acceptance Criteria:**

- Given `SYNTHESIS_SIGNAL_COUNT` is less than 5, `VERDICT` is `UNVERIFIABLE`
- `CONFIDENCE_SCORE` is not emitted
- `VERDICT_NARRATIVE` explains insufficient evidence

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "Unverifiable verdict is emitted when signal count is too low"

---

## FR-016: Confidence-to-Verdict Mapping

**Description:** The synthesizer must map computed confidence scores to PolitiFact-equivalent verdict labels using fixed thresholds. The mapping covers the full 0.0–1.0 range.

**Acceptance Criteria:**

- Score 0.95 maps to `TRUE`
- Score 0.77 maps to `MOSTLY_TRUE`
- Score 0.55 maps to `HALF_TRUE`
- Score 0.35 maps to `MOSTLY_FALSE`
- Score 0.18 maps to `FALSE`
- Score 0.04 maps to `PANTS_FIRE`

**Source:** `docs/features/verdict-synthesis.feature` — Scenario Outline: "Confidence score maps to correct PolitiFact-equivalent verdict"

---

## FR-017: ClaimReview Agreement — No Override

**Description:** When the synthesizer's computed verdict agrees with the ClaimReview verdict, no override reason is recorded. This is the normal-path case.

**Acceptance Criteria:**

- Given `CLAIMREVIEW_VERDICT = "FALSE"` and the synthesizer computes `VERDICT = "FALSE"`, `SYNTHESIS_OVERRIDE_REASON` is empty

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "Synthesizer agrees with ClaimReview verdict — no override recorded"

---

## FR-018: ClaimReview Disagreement — Override Recorded

**Description:** When the synthesizer's computed verdict diverges from the ClaimReview verdict, an override reason must be recorded that references the evidence that drove the divergence (e.g., domain evidence findings).

**Acceptance Criteria:**

- Given `CLAIMREVIEW_VERDICT = "TRUE"` and `DOMAIN_EVIDENCE_ALIGNMENT = "CONTRADICTS"`, the synthesizer computes `VERDICT = "MOSTLY_FALSE"`
- `SYNTHESIS_OVERRIDE_REASON` is non-empty
- `SYNTHESIS_OVERRIDE_REASON` references the domain evidence finding

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "Synthesizer disagrees with ClaimReview verdict — override recorded"
