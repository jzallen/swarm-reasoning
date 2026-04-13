---
id: FR-observation-resolution
title: "Observation Resolution"
status: accepted
category: functional
priority: must
components: [synthesizer]
date: 2026-04-13
---

# Observation Resolution

Functional requirements governing how the synthesizer resolves the authoritative value for each observation code when multiple observations exist (corrections, cancellations, preliminary data). These rules determine which observations enter the synthesis input set.

---

## FR-008: C-Status Resolution

**Description:** When corrections exist for an observation code (status `C`), the synthesizer must use the latest C-status observation as the authoritative value, superseding any prior F-status observations for that code.

**Acceptance Criteria:**

- Given multiple observations for the same code with both F and C statuses, the resolved value equals the latest C-status observation's value
- The resolution method is recorded as `LATEST_C`

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "Synthesizer uses latest C-status observation when corrections exist"

---

## FR-009: F-Status Resolution

**Description:** When no corrections exist for an observation code, the synthesizer must use the latest F-status observation as the authoritative value.

**Acceptance Criteria:**

- Given observations for a code with only F-status entries, the resolved value equals the latest F-status observation's value
- The resolution method is recorded as `LATEST_F`

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "Synthesizer uses latest F-status observation when no corrections exist"

---

## FR-010: X-Status Exclusion

**Description:** Observations with status `X` (cancelled) must be excluded from the synthesis input set entirely. Cancelled observations must not contribute to signal counts.

**Acceptance Criteria:**

- X-status observations are not included in the synthesis input set
- `SYNTHESIS_SIGNAL_COUNT` does not count cancelled observations

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "Synthesizer excludes X-status observations from synthesis"

---

## FR-011: P-Status Exclusion

**Description:** Observations with status `P` (preliminary) must be excluded from the synthesis input set. The synthesizer must record a warning when preliminary data is encountered, as it indicates incomplete upstream processing.

**Acceptance Criteria:**

- P-status observations are not included in the synthesis input set
- A warning is recorded in `VERDICT_NARRATIVE` noting incomplete coverage data

**Source:** `docs/features/verdict-synthesis.feature` — Scenario: "Synthesizer excludes P-status observations from synthesis"
