# feature: validation-baseline
# Covers the system's accuracy against the 50-claim PolitiFact validation
# corpus. Scenarios are structured to test each corpus category separately
# and to demonstrate swarm value on claims not yet indexed in ClaimReview.
#
# The corpus is defined in docs/validation/corpus.json (assembled separately,
# not generated — see ADR-008).
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Validation Baseline

  Background:
    Given the validation corpus is loaded from "docs/validation/corpus.json"
    And the orchestrator is running with all 11 agents healthy
    And the Google Fact Check Tools API is reachable
    And NewsAPI is reachable
    And the Media Bias Fact Check source list is loaded

  # ---------------------------------------------------------------------------
  # Corpus Category 1 — True / Mostly True (10 claims)
  # ---------------------------------------------------------------------------

  Scenario: System correctly identifies true claims
    Given the validation corpus category "TRUE_MOSTLY_TRUE" containing 10 claims
    When the system processes all 10 claims to completed state
    Then at least 7 of 10 verdicts map to TRUE or MOSTLY_TRUE
    And no verdict maps to FALSE or PANTS_FIRE
    And the mean CONFIDENCE_SCORE for the category is above 0.70

  # ---------------------------------------------------------------------------
  # Corpus Category 2 — False / Pants on Fire (10 claims)
  # ---------------------------------------------------------------------------

  Scenario: System correctly identifies false claims
    Given the validation corpus category "FALSE_PANTS_FIRE" containing 10 claims
    When the system processes all 10 claims to completed state
    Then at least 7 of 10 verdicts map to FALSE or PANTS_FIRE
    And no verdict maps to TRUE or MOSTLY_TRUE
    And the mean CONFIDENCE_SCORE for the category is below 0.25

  # ---------------------------------------------------------------------------
  # Corpus Category 3 — Half True (10 claims)
  # ---------------------------------------------------------------------------

  Scenario: System handles ambiguous claims without overclaiming
    Given the validation corpus category "HALF_TRUE" containing 10 claims
    When the system processes all 10 claims to completed state
    Then at least 5 of 10 verdicts map to HALF_TRUE or MOSTLY_TRUE or MOSTLY_FALSE
    And SYNTHESIS_SIGNAL_COUNT is above 10 for all 10 runs
    And no claim in this category reaches UNVERIFIABLE verdict

  # ---------------------------------------------------------------------------
  # Corpus Category 4 — ClaimReview Indexed (10 claims)
  # ---------------------------------------------------------------------------

  Scenario: System matches ClaimReview verdicts for indexed claims
    Given the validation corpus category "CLAIMREVIEW_INDEXED" containing 10 claims
    When the system processes all 10 claims to completed state
    Then CLAIMREVIEW_MATCH is TRUE for all 10 runs
    And CLAIMREVIEW_MATCH_SCORE is above 0.75 for all 10 runs
    And the system verdict matches the ClaimReview verdict for at least 8 of 10 claims
    And SYNTHESIS_OVERRIDE_REASON is non-empty for any claim where verdicts diverge

  # ---------------------------------------------------------------------------
  # Corpus Category 5 — Not ClaimReview Indexed (10 claims)
  # This is the key proof-of-value category.
  # A single agent calling ClaimReview would return no match for these claims.
  # The swarm must reason from coverage analysis and domain evidence alone.
  # ---------------------------------------------------------------------------

  Scenario: Swarm produces verdicts for claims not in ClaimReview
    Given the validation corpus category "NOT_CLAIMREVIEW_INDEXED" containing 10 claims
    When the system processes all 10 claims to completed state
    Then CLAIMREVIEW_MATCH is FALSE for all 10 runs
    And no claim reaches UNVERIFIABLE verdict
    And SYNTHESIS_SIGNAL_COUNT is above 8 for all 10 runs
    And the system verdict aligns with the PolitiFact ground truth for at least 6 of 10 claims

  Scenario: Swarm outperforms single-agent baseline on non-indexed claims
    Given the validation corpus category "NOT_CLAIMREVIEW_INDEXED" containing 10 claims
    And a single-agent baseline has been run on the same 10 claims
    When system verdicts are compared to baseline verdicts
    Then the swarm correct alignment rate exceeds the baseline correct alignment rate
    And the swarm mean SYNTHESIS_SIGNAL_COUNT exceeds the baseline signal count by at least 5

  # ---------------------------------------------------------------------------
  # Cross-Cutting Validation Properties
  # ---------------------------------------------------------------------------

  Scenario: Every published run has a queryable audit log
    Given all 50 corpus claims have been processed to completed state
    When a user fetches any verdict via GET "/sessions/{sessionId}/verdict"
    Then the observation streams for that run exist in Redis
    And the streams contain observations from at least 8 distinct agents

  Scenario: No run reaches completed state with fewer than 5 synthesis signals
    Given all 50 corpus claims have been processed
    Then no completed run has SYNTHESIS_SIGNAL_COUNT below 5
    And any run with SYNTHESIS_SIGNAL_COUNT below 5 has VERDICT = "UNVERIFIABLE"

  Scenario: Blindspot detection correlates with lower confidence scores
    Given all 50 corpus claims have been processed
    When runs are grouped by BLINDSPOT_SCORE above 0.7 vs below 0.3
    Then the mean CONFIDENCE_SCORE for the high-blindspot group is lower
    And the difference in mean CONFIDENCE_SCORE between groups is statistically significant

  Scenario: Total run time for a single claim does not exceed 120 seconds
    Given a claim from the validation corpus
    When the claim is submitted and the run completes to completed state
    Then the elapsed time between POST /sessions/{sessionId}/claims and completed status is under 120 seconds
    And the parallel fan-out phase (agents 4-9) completes in under 45 seconds
