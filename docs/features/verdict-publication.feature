# feature: verdict-publication
# Covers observation resolution for consumer output, schema validation,
# required JSON fields, error handling, and Backend API delivery.
# Replaces edge-serialization.feature — no edge adapter is needed because
# observations are natively JSON (ADR-011).
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Verdict Publication

  Background:
    Given the orchestrator is running
    And the observation code registry is loaded

  # ---------------------------------------------------------------------------
  # Trigger Conditions
  # ---------------------------------------------------------------------------

  Scenario: Publication activates when synthesizer publishes STOP with F-status
    Given run "RUN-001" has reached synthesizing state
    And the synthesizer has published a STOP message with finalStatus "F"
    When the orchestrator detects the STOP message via XREADGROUP
    Then the orchestrator notifies the Backend API of run completion
    And the Backend API begins reading observations from Redis Streams

  Scenario: Publication does not activate on preliminary verdict
    Given the synthesizer has published a VERDICT observation with status "P"
    But the synthesizer has not yet published a STOP message
    Then the Backend API does NOT attempt to read finalized observations

  # ---------------------------------------------------------------------------
  # Observation Resolution During Publication
  # ---------------------------------------------------------------------------

  Scenario: Backend API resolves corrections before constructing verdict response
    Given the observation streams for run "RUN-001" contain:
      | seq | code              | value     | status | agent              |
      | 14  | CLAIMREVIEW_VERDICT | HALF_TRUE | F    | claimreview-matcher |
      | 31  | CLAIMREVIEW_VERDICT | FALSE     | C    | claimreview-matcher |
    When the Backend API constructs the verdict response
    Then the JSON field "claimreview_verdict" equals "FALSE"
    And the JSON does not contain "HALF_TRUE" for claimreview_verdict

  Scenario: Backend API excludes X-status observations from verdict response
    Given the observation streams contain a DOMAIN_CONFIDENCE observation with status X
    When the Backend API constructs the verdict response
    Then the JSON output does not contain a "domain_confidence" field

  # ---------------------------------------------------------------------------
  # Required JSON Fields
  # ---------------------------------------------------------------------------

  Scenario: Verdict response contains all required top-level fields
    Given run "RUN-001" has been processed to completed state
    When the Backend API constructs the verdict response
    Then the JSON output contains all of the following fields:
      | field                    |
      | run_id                   |
      | claim_id                 |
      | claim_text               |
      | verdict                  |
      | confidence_score         |
      | narrative                |
      | coverage                 |
      | blindspot_score          |
      | blindspot_direction      |
      | claimreview_match        |
      | synthesis_signal_count   |
      | domain_evidence_alignment|
      | generated_at             |

  Scenario: Coverage field contains sub-objects for left, center, and right
    When the Backend API constructs a verdict response for a completed run
    Then the JSON "coverage" field contains keys "left", "center", and "right"
    And each sub-object contains "article_count" and "framing"
    And each sub-object contains "top_source" if a COVERAGE_TOP_SOURCE observation exists

  # ---------------------------------------------------------------------------
  # Schema Validation
  # ---------------------------------------------------------------------------

  Scenario: Publication succeeds when all required fields are present
    Given a well-formed observation set for run "RUN-001"
    When the Backend API validates the constructed verdict JSON
    Then schema validation passes
    And the verdict is persisted
    And the run status transitions to completed

  Scenario: Schema validation fails if VERDICT is not in controlled vocabulary
    Given the synthesizer published VERDICT = "UNCERTAIN" (not in the controlled vocabulary)
    When the Backend API validates the constructed verdict JSON
    Then schema validation fails
    And the run error log records the failure with the run_id and field name

  Scenario: Schema validation fails if confidence_score is outside 0.0-1.0
    Given the CONFIDENCE_SCORE observation contains value 1.42
    When the Backend API validates the constructed verdict JSON
    Then schema validation fails

  Scenario: Schema validation failure does not retry automatically
    Given schema validation has failed for run "RUN-001"
    Then the orchestrator does not re-dispatch the synthesizer
    And the run remains in failed state pending manual investigation

  # ---------------------------------------------------------------------------
  # Backend API Delivery
  # ---------------------------------------------------------------------------

  Scenario: Verdict is queryable via session endpoint after successful publication
    Given the Backend API has successfully published the verdict for session "SESSION-001"
    When an analyst issues GET "/sessions/SESSION-001/verdict"
    Then the response status is 200
    And the response body matches the verdict response

  Scenario: Session endpoint returns verdict with full citation history
    Given session "SESSION-001" has a completed run with a published verdict
    When an analyst issues GET "/sessions/SESSION-001/verdict"
    Then the response contains the published verdict for session "SESSION-001"
    And the verdict includes citations ordered by generated_at descending

  Scenario: Run transitions to completed after verdict is persisted
    Given the Backend API constructs and validates the verdict for session "SESSION-001"
    When the verdict is persisted
    Then the run status transitions to "completed"
    And the session status transitions to "frozen"
    And GET "/sessions/SESSION-001" returns session status "frozen"
