# feature: claim-ingestion
# Covers claim submission, ingestion agent behaviour, detection, entity
# extraction, and the check-worthiness gate that controls whether a run
# proceeds to analysis or is cancelled.
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Claim Ingestion

  Background:
    Given the orchestrator is running
    And all agent bundles are healthy and registered
    And the OBX code registry is loaded into YottaDB

  # ---------------------------------------------------------------------------
  # Claim Submission
  # ---------------------------------------------------------------------------

  Scenario: Operator submits a valid claim
    When an operator POSTs to "/claims" with body:
      """
      {
        "claim_text": "Biden issued a federal vaccine mandate for all private employers.",
        "source_url": "https://example.com/article",
        "source_date": "20211104"
      }
      """
    Then the response status is 202
    And the response body contains a "run_id"
    And the response body contains "status": "INGESTED"
    And the response body contains a "poll_url"
    And a run record exists in orchestrator YottaDB with status "INGESTED"

  Scenario: Submission is rejected if claim_text is missing
    When an operator POSTs to "/claims" with body:
      """
      {
        "source_url": "https://example.com/article"
      }
      """
    Then the response status is 422
    And the response body contains an error referencing "claim_text"

  Scenario: Submission is rejected if claim_text exceeds 1000 characters
    When an operator POSTs to "/claims" with a claim_text of 1001 characters
    Then the response status is 422
    And the response body contains an error referencing "claim_text"

  Scenario: Duplicate claim text produces a new run against the same claim_id
    Given a claim with text "Biden issued a federal vaccine mandate for all private employers." already exists
    When an operator POSTs the same claim_text again
    Then the response status is 202
    And the new run record references the existing claim_id
    And a second run record is created with a distinct run_id

  # ---------------------------------------------------------------------------
  # Ingestion Agent
  # ---------------------------------------------------------------------------

  Scenario: Ingestion agent writes required OBX rows
    Given a run "RUN-001" has been initiated for claim "CLAIM-001"
    When the ingestion agent completes its task
    Then YottaDB contains an F-status OBX row for code "CLAIM_TEXT" in run "RUN-001"
    And YottaDB contains an F-status OBX row for code "CLAIM_SOURCE_URL" in run "RUN-001"
    And YottaDB contains an F-status OBX row for code "CLAIM_SOURCE_DATE" in run "RUN-001"
    And YottaDB contains an F-status OBX row for code "CLAIM_DOMAIN" in run "RUN-001"
    And the orchestrator Mirth receives an ACK AA from ingestion-agent

  Scenario: Ingestion agent OBX rows are attributed correctly
    Given a run "RUN-001" has been initiated for claim "CLAIM-001"
    When the ingestion agent completes its task
    Then all OBX rows written by ingestion-agent have OBX.16 = "ingestion-agent"

  Scenario: HL7v2 escape sequences are applied to claim text containing pipe characters
    Given a claim_text contains the string "Congress passed the bill | the president signed it"
    When the ingestion agent writes the CLAIM_TEXT OBX row
    Then the stored OBX value contains "\F\" in place of "|"
    And the raw HL7v2 segment is parseable without field count errors

  # ---------------------------------------------------------------------------
  # Claim Detection
  # ---------------------------------------------------------------------------

  Scenario: Check-worthy claim proceeds to ANALYZING
    Given the ingestion agent has completed for run "RUN-001"
    When the claim-detector emits CHECK_WORTHY_SCORE = 0.82
    Then the run status transitions to "ANALYZING"
    And the orchestrator dispatches the entity-extractor

  Scenario: Below-threshold claim is cancelled
    Given the ingestion agent has completed for run "RUN-001"
    When the claim-detector emits CHECK_WORTHY_SCORE = 0.31
    Then the run status transitions to "CANCELLED"
    And no further agents are dispatched
    And GET "/runs/RUN-001" returns status "CANCELLED"
    And the YottaDB OBX log for "RUN-001" is retained

  Scenario: Claim detector writes normalized claim text
    Given the ingestion agent has completed for run "RUN-001"
    When the claim-detector completes its task
    Then YottaDB contains an F-status OBX row for code "CLAIM_NORMALIZED" in run "RUN-001"
    And the CLAIM_NORMALIZED value is lowercase
    And the CLAIM_NORMALIZED value does not contain hedging phrases like "reportedly" or "allegedly"

  # ---------------------------------------------------------------------------
  # Entity Extraction
  # ---------------------------------------------------------------------------

  Scenario: Entity extractor writes one OBX row per extracted entity
    Given the claim-detector has completed for run "RUN-001" with score 0.82
    And the claim text contains two named persons, one organization, and one date
    When the entity-extractor completes its task
    Then YottaDB contains exactly 2 F-status OBX rows for code "ENTITY_PERSON" in run "RUN-001"
    And YottaDB contains exactly 1 F-status OBX row for code "ENTITY_ORG" in run "RUN-001"
    And YottaDB contains exactly 1 F-status OBX row for code "ENTITY_DATE" in run "RUN-001"

  Scenario: Entity extractor emits no ENTITY_STATISTIC rows for claims without numeric content
    Given the claim text contains no numeric quantities
    When the entity-extractor completes its task
    Then YottaDB contains zero OBX rows for code "ENTITY_STATISTIC" in run "RUN-001"

  Scenario: Completion of entity extraction triggers Phase 2 fan-out
    Given the entity-extractor has completed for run "RUN-001"
    When the orchestrator processes the entity-extractor ACK
    Then the orchestrator dispatches claimreview-matcher via MCP
    And the orchestrator dispatches coverage-left via MCP
    And the orchestrator dispatches coverage-center via MCP
    And the orchestrator dispatches coverage-right via MCP
    And the orchestrator dispatches domain-evidence via MCP
    And all five dispatches occur within 500ms of one another
