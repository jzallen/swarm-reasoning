# feature: edge-serialization
# Covers HL7v2 to FHIR-like JSON transformation, schema validation,
# field mapping from OBX code registry, error handling, and consumer
# API delivery.
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Edge Serialization

  Background:
    Given the orchestrator is running
    And the edge adapter Mirth channel is active
    And the OBX code registry is loaded

  # ---------------------------------------------------------------------------
  # Trigger Conditions
  # ---------------------------------------------------------------------------

  Scenario: Edge adapter activates on receipt of VERDICT F-status OBX
    Given run "RUN-001" has reached SYNTHESIZED state
    And the synthesizer has sent the finalized HL7v2 message to orchestrator Mirth
    When orchestrator Mirth inspects the message
    Then it detects a VERDICT OBX row with result_status = "F"
    And it routes the message to the edge adapter channel
    And it does NOT route the message to the edge adapter for messages without a VERDICT F row

  Scenario: Edge adapter does not activate on preliminary verdict
    Given a message contains a VERDICT OBX row with result_status = "P"
    When orchestrator Mirth inspects the message
    Then it does NOT route the message to the edge adapter channel

  # ---------------------------------------------------------------------------
  # OBX Resolution During Serialization
  # ---------------------------------------------------------------------------

  Scenario: Edge adapter resolves corrections before mapping to JSON
    Given the finalized HL7v2 message contains:
      | seq | code             | value        | status |
      | 14  | CLAIMREVIEW_VERDICT | HALF_TRUE | F      |
      | 31  | CLAIMREVIEW_VERDICT | FALSE      | C      |
    When the edge adapter serializes the message
    Then the JSON field "claimreview_verdict" equals "FALSE"
    And the JSON does not contain "HALF_TRUE" for claimreview_verdict

  Scenario: Edge adapter excludes X-status observations from JSON output
    Given the finalized message contains a DOMAIN_CONFIDENCE OBX row with status X
    When the edge adapter serializes the message
    Then the JSON output does not contain a "domain_confidence" field

  # ---------------------------------------------------------------------------
  # Required JSON Fields
  # ---------------------------------------------------------------------------

  Scenario: Serialized JSON contains all required top-level fields
    Given run "RUN-001" has been processed to SYNTHESIZED state
    When the edge adapter serializes the finalized message
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
      | audit_log_ref            |
      | generated_at             |

  Scenario: Coverage field contains sub-objects for left, center, and right
    When the edge adapter serializes a completed run
    Then the JSON "coverage" field contains keys "left", "center", and "right"
    And each sub-object contains "article_count" and "framing"
    And each sub-object contains "top_source" if a COVERAGE_TOP_SOURCE row exists

  Scenario: audit_log_ref points to the correct YottaDB file
    When the edge adapter serializes run "RUN-001"
    Then the JSON "audit_log_ref" field equals "RUN-001.hl7"
    And a file matching "RUN-001.hl7" exists in YottaDB storage

  # ---------------------------------------------------------------------------
  # Schema Validation
  # ---------------------------------------------------------------------------

  Scenario: Serialization succeeds when all required fields are present
    Given a well-formed finalized HL7v2 message for run "RUN-001"
    When the edge adapter validates the constructed JSON
    Then schema validation passes
    And the JSON is posted to the Consumer API internal endpoint
    And the Consumer API responds with 201 Created

  Scenario: Schema validation fails if VERDICT is not in controlled vocabulary
    Given the synthesizer wrote VERDICT = "UNCERTAIN" (not in the controlled vocabulary)
    When the edge adapter validates the constructed JSON
    Then schema validation fails
    And the edge adapter sends ACK AE to orchestrator Mirth
    And the run error log records the failure with the run_id and field name

  Scenario: Schema validation fails if confidence_score is outside 0.0–1.0
    Given the CONFIDENCE_SCORE OBX row contains value 1.42
    When the edge adapter validates the constructed JSON
    Then schema validation fails
    And the edge adapter sends ACK AE to orchestrator Mirth

  Scenario: Schema validation failure does not retry automatically
    Given schema validation has failed for run "RUN-001"
    Then the orchestrator does not re-dispatch the synthesizer
    And the run remains in SYNTHESIZED state pending manual investigation
    And an operator can retrieve the raw HL7v2 message via GET "/runs/RUN-001/hl7"

  # ---------------------------------------------------------------------------
  # Consumer API Delivery
  # ---------------------------------------------------------------------------

  Scenario: Verdict is queryable by run_id after successful serialization
    Given the edge adapter has successfully posted the JSON verdict for run "RUN-001"
    When an analyst issues GET "/verdicts?run_id=RUN-001"
    Then the response status is 200
    And the response body matches the serialized JSON verdict

  Scenario: Verdict is queryable by claim_id after successful serialization
    Given multiple runs exist for claim "CLAIM-001"
    When an analyst issues GET "/verdicts?claim_id=CLAIM-001"
    Then the response contains all published verdicts for claim "CLAIM-001"
    And results are ordered by generated_at descending

  Scenario: Run transitions to PUBLISHED after Consumer API confirms receipt
    Given the edge adapter posts the verdict JSON to the Consumer API
    When the Consumer API responds with 201 Created
    Then the run status in orchestrator YottaDB transitions to "PUBLISHED"
    And GET "/runs/RUN-001" returns status "PUBLISHED"
