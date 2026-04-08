# feature: verdict-synthesis
# Covers synthesizer OBX resolution logic, confidence score computation,
# verdict mapping, override behaviour, and narrative generation.
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Verdict Synthesis

  Background:
    Given the orchestrator is running
    And all 10 agents have emitted terminal OBX status for run "RUN-001"
    And the orchestrator has assembled the consolidated OBX log

  # ---------------------------------------------------------------------------
  # OBX Resolution
  # ---------------------------------------------------------------------------

  Scenario: Synthesizer uses latest C-status row when corrections exist
    Given the OBX log for run "RUN-001" contains:
      | seq | code             | value | status |
      | 14  | CONFIDENCE_SCORE | 0.72  | F      |
      | 31  | CONFIDENCE_SCORE | 0.61  | C      |
    When the synthesizer resolves the authoritative CONFIDENCE_SCORE value
    Then the resolved value is 0.61
    And the resolution method is "LATEST_C"

  Scenario: Synthesizer uses latest F-status row when no corrections exist
    Given the OBX log for run "RUN-001" contains:
      | seq | code                    | value     | status |
      | 5   | CLAIMREVIEW_VERDICT     | FALSE     | F      |
    When the synthesizer resolves the authoritative CLAIMREVIEW_VERDICT value
    Then the resolved value is "FALSE"
    And the resolution method is "LATEST_F"

  Scenario: Synthesizer excludes X-status observations from synthesis
    Given the OBX log for run "RUN-001" contains:
      | seq | code              | value  | status |
      | 9   | DOMAIN_CONFIDENCE | 0.85   | X      |
    When the synthesizer builds its input set
    Then DOMAIN_CONFIDENCE is not included in the synthesis input set
    And SYNTHESIS_SIGNAL_COUNT does not count the cancelled observation

  Scenario: Synthesizer excludes P-status observations from synthesis
    Given the OBX log contains a COVERAGE_FRAMING row with status P
    When the synthesizer builds its input set
    Then the P-status COVERAGE_FRAMING row is not included
    And a warning is recorded in VERDICT_NARRATIVE noting incomplete coverage data

  # ---------------------------------------------------------------------------
  # Confidence Score Computation
  # ---------------------------------------------------------------------------

  Scenario: Full evidence set produces a well-calibrated confidence score
    Given the resolved OBX inputs include:
      | code                        | value       |
      | CLAIMREVIEW_MATCH           | TRUE        |
      | CLAIMREVIEW_VERDICT         | FALSE       |
      | DOMAIN_EVIDENCE_ALIGNMENT   | CONTRADICTS |
      | CROSS_SPECTRUM_CORROBORATION| TRUE        |
      | BLINDSPOT_SCORE             | 0.12        |
    When the synthesizer computes CONFIDENCE_SCORE
    Then CONFIDENCE_SCORE is between 0.25 and 0.44
    And the VERDICT is "MOSTLY_FALSE"

  Scenario: Missing ClaimReview match reduces confidence score
    Given CLAIMREVIEW_MATCH is FALSE
    And DOMAIN_EVIDENCE_ALIGNMENT is CONTRADICTS
    And CROSS_SPECTRUM_CORROBORATION is TRUE
    When the synthesizer computes CONFIDENCE_SCORE
    Then CONFIDENCE_SCORE is lower than the equivalent scenario with CLAIMREVIEW_MATCH TRUE

  Scenario: High blindspot score penalizes confidence score
    Given BLINDSPOT_SCORE is 0.90
    When the synthesizer computes CONFIDENCE_SCORE
    Then CONFIDENCE_SCORE is reduced by the blindspot penalty
    And VERDICT_NARRATIVE references the blindspot as a confidence-reducing factor

  Scenario: Unverifiable verdict is emitted when signal count is too low
    Given SYNTHESIS_SIGNAL_COUNT is less than 5
    When the synthesizer computes the verdict
    Then VERDICT is "UNVERIFIABLE"
    And CONFIDENCE_SCORE is not emitted
    And VERDICT_NARRATIVE explains insufficient evidence

  # ---------------------------------------------------------------------------
  # Verdict Mapping
  # ---------------------------------------------------------------------------

  Scenario Outline: Confidence score maps to correct PolitiFact-equivalent verdict
    Given CONFIDENCE_SCORE is <score>
    When the synthesizer maps score to verdict
    Then VERDICT is "<verdict>"

    Examples:
      | score | verdict       |
      | 0.95  | TRUE          |
      | 0.77  | MOSTLY_TRUE   |
      | 0.55  | HALF_TRUE     |
      | 0.35  | MOSTLY_FALSE  |
      | 0.18  | FALSE         |
      | 0.04  | PANTS_FIRE    |

  # ---------------------------------------------------------------------------
  # ClaimReview Override
  # ---------------------------------------------------------------------------

  Scenario: Synthesizer agrees with ClaimReview verdict — no override recorded
    Given CLAIMREVIEW_VERDICT is "FALSE"
    And the synthesizer computes VERDICT as "FALSE"
    When the synthesizer emits its OBX rows
    Then SYNTHESIS_OVERRIDE_REASON is empty

  Scenario: Synthesizer disagrees with ClaimReview verdict — override recorded
    Given CLAIMREVIEW_VERDICT is "TRUE"
    And DOMAIN_EVIDENCE_ALIGNMENT is "CONTRADICTS"
    And the synthesizer computes VERDICT as "MOSTLY_FALSE"
    When the synthesizer emits its OBX rows
    Then SYNTHESIS_OVERRIDE_REASON is non-empty
    And SYNTHESIS_OVERRIDE_REASON references the domain evidence finding

  # ---------------------------------------------------------------------------
  # Synthesizer OBX Output
  # ---------------------------------------------------------------------------

  Scenario: Synthesizer emits all required OBX rows with F status
    When the synthesizer completes synthesis for run "RUN-001"
    Then YottaDB contains an F-status OBX row for code "CONFIDENCE_SCORE"
    And YottaDB contains an F-status OBX row for code "VERDICT"
    And YottaDB contains an F-status OBX row for code "VERDICT_NARRATIVE"
    And YottaDB contains an F-status OBX row for code "SYNTHESIS_SIGNAL_COUNT"
    And YottaDB contains an F-status OBX row for code "SYNTHESIS_OVERRIDE_REASON"
    And all five rows have OBX.16 = "synthesizer"

  Scenario: Synthesizer sends finalized HL7v2 message via Mirth
    When the synthesizer completes synthesis for run "RUN-001"
    Then synthesizer Mirth sends an HL7v2 message to orchestrator Mirth
    And the message contains all OBX rows from all agents in sequence order
    And the message contains the synthesizer verdict rows as the final OBX rows
    And orchestrator Mirth responds with ACK AA

  Scenario: Run transitions to SYNTHESIZED after synthesizer ACK
    Given the synthesizer Mirth has sent the finalized message
    When orchestrator Mirth receives and ACKs the finalized message
    Then the run status in orchestrator YottaDB transitions to "SYNTHESIZED"
    And the orchestrator Mirth routes the message to the edge adapter channel
