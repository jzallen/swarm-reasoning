---
id: FR-publication-schema
title: "Verdict Publication and Schema Validation"
status: accepted
category: functional
priority: must
components: [backend-api, orchestrator, synthesizer]
date: 2026-04-13
---

# Verdict Publication and Schema Validation

Functional requirements governing verdict publication trigger conditions, observation resolution during publication, required JSON schema fields, schema validation rules, and Backend API delivery.

---

## FR-031: Publication Trigger on Synthesizer STOP

**Description:** Verdict publication activates when the synthesizer publishes a STOP message with `finalStatus: "F"`. The orchestrator detects the STOP via XREADGROUP and notifies the Backend API to begin reading finalized observations from Redis Streams.

**Acceptance Criteria:**

- When the synthesizer publishes a STOP message with `finalStatus: "F"`, the orchestrator notifies the Backend API of run completion
- The Backend API begins reading observations from Redis Streams

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Publication activates when synthesizer publishes STOP with F-status"

---

## FR-032: No Publication on Preliminary Verdict

**Description:** The Backend API must not attempt to read finalized observations while the synthesizer has only published preliminary (P-status) observations and has not yet published a STOP message.

**Acceptance Criteria:**

- Given the synthesizer has published a VERDICT observation with status `P` but no STOP message, the Backend API does NOT attempt to read finalized observations

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Publication does not activate on preliminary verdict"

---

## FR-033: Correction Resolution During Publication

**Description:** When constructing the verdict response, the Backend API must resolve corrections by using the latest C-status observation for any code that has been corrected, superseding earlier F-status values.

**Acceptance Criteria:**

- Given observations for `CLAIMREVIEW_VERDICT` with an F-status value of `HALF_TRUE` and a later C-status value of `FALSE`, the JSON field `claimreview_verdict` equals `FALSE`
- The JSON does not contain the superseded value

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Backend API resolves corrections before constructing verdict response"

---

## FR-034: X-Status Exclusion During Publication

**Description:** Observations with status `X` (cancelled) must be excluded from the verdict response entirely. No JSON field is generated for a cancelled observation.

**Acceptance Criteria:**

- Given a `DOMAIN_CONFIDENCE` observation with status `X`, the verdict JSON does not contain a `domain_confidence` field

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Backend API excludes X-status observations from verdict response"

---

## FR-035: Required Verdict JSON Fields

**Description:** The verdict response JSON must contain all required top-level fields that fully describe the claim, verdict, evidence basis, and metadata.

**Acceptance Criteria:**

- The JSON output contains all of the following fields: `run_id`, `claim_id`, `claim_text`, `verdict`, `confidence_score`, `narrative`, `coverage`, `blindspot_score`, `blindspot_direction`, `claimreview_match`, `synthesis_signal_count`, `domain_evidence_alignment`, `generated_at`

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Verdict response contains all required top-level fields"

---

## FR-036: Coverage Field Structure

**Description:** The `coverage` field in the verdict JSON must contain sub-objects for `left`, `center`, and `right`, each containing article count and framing data from the corresponding coverage agent.

**Acceptance Criteria:**

- The `coverage` field contains keys `left`, `center`, and `right`
- Each sub-object contains `article_count` and `framing`
- Each sub-object contains `top_source` if a `COVERAGE_TOP_SOURCE` observation exists

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Coverage field contains sub-objects for left, center, and right"

---

## FR-037: Successful Schema Validation

**Description:** When all required fields are present and valid, schema validation must pass, the verdict must be persisted, and the run status must transition to completed.

**Acceptance Criteria:**

- Given a well-formed observation set, schema validation passes
- The verdict is persisted
- The run status transitions to `completed`

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Publication succeeds when all required fields are present"

---

## FR-038: Verdict Controlled Vocabulary Validation

**Description:** The `VERDICT` field must be a member of the controlled vocabulary (TRUE, MOSTLY_TRUE, HALF_TRUE, MOSTLY_FALSE, FALSE, PANTS_FIRE, UNVERIFIABLE). Any value outside this set must fail schema validation.

**Acceptance Criteria:**

- Given `VERDICT = "UNCERTAIN"` (not in controlled vocabulary), schema validation fails
- The run error log records the failure with the `run_id` and field name

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Schema validation fails if VERDICT is not in controlled vocabulary"

---

## FR-039: Confidence Score Range Validation

**Description:** The `CONFIDENCE_SCORE` field must be a decimal value in the range 0.0–1.0 inclusive. Values outside this range must fail schema validation.

**Acceptance Criteria:**

- Given `CONFIDENCE_SCORE = 1.42`, schema validation fails

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Schema validation fails if confidence_score is outside 0.0-1.0"

---

## FR-040: No Automatic Retry on Validation Failure

**Description:** When schema validation fails, the orchestrator must not re-dispatch the synthesizer. The run remains in failed state pending manual investigation.

**Acceptance Criteria:**

- Given schema validation has failed, the orchestrator does not re-dispatch the synthesizer
- The run remains in `failed` state pending manual investigation

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Schema validation failure does not retry automatically"

---

## FR-041: Verdict Queryable via Session Endpoint

**Description:** After successful publication, the verdict must be queryable via the session endpoint. The response body must match the published verdict.

**Acceptance Criteria:**

- Given a successfully published verdict for a session, `GET /sessions/{sessionId}/verdict` returns status 200
- The response body matches the published verdict

**Source:** `docs/features/verdict-publication.feature` — Scenario: "Verdict is queryable via session endpoint after successful publication"
