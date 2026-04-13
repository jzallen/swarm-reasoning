# feature: error-experience
# Covers user-facing error handling: rate limiting, agent failure with
# partial results, network disconnect/reconnect for SSE, and total
# agent failure. Ensures the frontend degrades gracefully and
# communicates actionable information to the user.
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Error Experience

  Background:
    Given the frontend is loaded in a browser
    And the Backend API is reachable

  # ---------------------------------------------------------------------------
  # Rate Limiting
  # ---------------------------------------------------------------------------

  Scenario: User is rate-limited after exceeding submission threshold
    Given the user has submitted claims exceeding the rate limit within the time window
    When the user submits another claim
    Then the response status is 429
    And the frontend displays a message indicating the user has been rate-limited
    And the message includes a retry-after duration

  Scenario: Rate-limited user can submit again after cooldown
    Given the user was rate-limited
    When the retry-after duration has elapsed
    And the user submits a new claim
    Then the response status is 202
    And claim processing begins normally

  # ---------------------------------------------------------------------------
  # Agent Failure with Partial Result
  # ---------------------------------------------------------------------------

  Scenario: Single agent failure does not block verdict
    Given a run "RUN-001" is in progress
    When coverage-left fails with an unrecoverable error
    And all other agents complete successfully
    Then the orchestrator proceeds to synthesis with available observations
    And the verdict is published with a reduced SYNTHESIS_SIGNAL_COUNT
    And the user sees a verdict with a note about incomplete coverage data

  Scenario: Partial result indicates which agents failed
    Given coverage-left failed during run "RUN-001"
    When the verdict is displayed to the user
    Then the verdict narrative references the missing left-leaning coverage analysis
    And the BLINDSPOT_SCORE reflects the coverage gap

  Scenario: Agent timeout is treated as failure
    Given coverage-right has not published a STOP message within the agent timeout period
    When the orchestrator marks coverage-right as timed out
    Then the orchestrator proceeds as if coverage-right failed
    And the user sees a progress message indicating the timeout

  # ---------------------------------------------------------------------------
  # Network Disconnect and Reconnect
  # ---------------------------------------------------------------------------

  Scenario: Frontend detects SSE connection loss
    Given the user is watching agent progress via SSE for run "RUN-001"
    When the network connection drops
    Then the frontend displays an indication that the connection was lost
    And previously received progress messages remain visible

  Scenario: Frontend reconnects automatically after network recovery
    Given the SSE connection was lost during run "RUN-001"
    When the network connection is restored
    Then the frontend re-establishes the SSE connection
    And the frontend receives any progress events that occurred during the disconnect
    And the progress display resumes without duplicate messages

  Scenario: Verdict is available after reconnect even if published during disconnect
    Given the SSE connection was lost during run "RUN-001"
    And the verdict was published while the user was disconnected
    When the network connection is restored
    Then the frontend fetches the completed verdict via the REST endpoint
    And the verdict is displayed to the user

  # ---------------------------------------------------------------------------
  # All Agents Fail
  # ---------------------------------------------------------------------------

  Scenario: Total agent failure produces a clear error message
    Given a run "RUN-001" is in progress
    When all agents fail with unrecoverable errors
    Then the run status transitions to "failed"
    And the frontend displays a message indicating the system could not process the claim
    And the message suggests the user try again later

  Scenario: Failed run does not produce a verdict
    Given run "RUN-001" has failed due to total agent failure
    When the user views the session
    Then no verdict is displayed
    And no CONFIDENCE_SCORE or VERDICT observation exists for the run

  Scenario: Failed run is visible in session history
    Given run "RUN-001" has failed
    When the user navigates to the session history
    Then the session shows status "failed"
    And the user can click the session to see the error details
