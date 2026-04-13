# Covers the user-facing claim submission journey through the chat interface:
# textarea input, validation feedback, API handshake, session creation, and URL
# persistence.  Scenarios test what the user sees, not internal agent behaviour.

Feature: Chat Submission
  As a user of the fact-checking application
  I want to submit a claim through the chat interface
  So that the swarm can evaluate its truthfulness

  Background:
    Given the backend API is reachable at "http://localhost:3000"
    And the frontend is loaded at "http://localhost:5173"

  # ---------------------------------------------------------------------------
  # Happy-path submission
  # ---------------------------------------------------------------------------

  Scenario: Submit a valid claim through the chat input
    Given the chat interface is in the idle state
    When the user types "The Great Wall of China is visible from space" into the claim textarea
    And the user clicks the "Check Claim" button
    Then the button label changes to "Submitting..."
    And the textarea becomes disabled
    And a POST request is sent to "/sessions" returning 201 with a sessionId
    And a POST request is sent to "/sessions/{sessionId}/claims" with body:
      | field     | value                                             |
      | claimText | The Great Wall of China is visible from space      |
    And the response status is 202
    And the claim appears in a user bubble above the progress stream
    And the browser URL updates to "/{sessionId}"
    And the chat phase transitions to "active"

  Scenario: Submit a claim using the Enter key
    Given the chat interface is in the idle state
    When the user types "Vitamin C cures the common cold" into the claim textarea
    And the user presses the Enter key
    Then a POST request is sent to "/sessions" returning 201
    And a POST request is sent to "/sessions/{sessionId}/claims" returning 202
    And the claim appears in a user bubble

  Scenario: Enter Shift+Enter inserts a newline instead of submitting
    Given the chat interface is in the idle state
    When the user types "Line one" into the claim textarea
    And the user presses Shift+Enter
    And the user types "Line two"
    Then no POST request is sent
    And the textarea contains "Line one\nLine two"

  # ---------------------------------------------------------------------------
  # Input validation — client side
  # ---------------------------------------------------------------------------

  Scenario: Submit button is disabled when textarea is empty
    Given the chat interface is in the idle state
    When the claim textarea is empty
    Then the "Check Claim" button is disabled

  Scenario: Submit button is disabled when textarea contains only whitespace
    Given the chat interface is in the idle state
    When the user types "   " into the claim textarea
    Then the "Check Claim" button is disabled

  Scenario: Leading and trailing whitespace is trimmed before submission
    Given the chat interface is in the idle state
    When the user types "  The earth is flat  " into the claim textarea
    And the user clicks the "Check Claim" button
    Then the POST to "/sessions/{sessionId}/claims" contains claimText "The earth is flat"

  # ---------------------------------------------------------------------------
  # Input validation — server side
  # ---------------------------------------------------------------------------

  Scenario: Server rejects a claim exceeding 2000 characters
    Given the chat interface is in the idle state
    When the user submits a claim of 2001 characters
    Then the backend responds with 400
    And an error banner displays "Failed to submit claim"
    And the chat phase transitions to "error"

  Scenario: Server rejects a request with unknown properties
    Given the chat interface is in the idle state
    When a POST to "/sessions/{sessionId}/claims" includes an unknown field "extra"
    Then the backend responds with 400

  # ---------------------------------------------------------------------------
  # Duplicate submission guard
  # ---------------------------------------------------------------------------

  Scenario: Duplicate claim submission is rejected with 409
    Given the user has already submitted "Earth orbits the Sun" to session {sessionId}
    When the user submits "A second claim" to the same session
    Then the backend responds with 409
    And an error banner is displayed

  # ---------------------------------------------------------------------------
  # Session not found
  # ---------------------------------------------------------------------------

  Scenario: Claim submission to a non-existent session returns 404
    Given a sessionId "00000000-0000-4000-a000-000000000000" that does not exist
    When a POST is sent to "/sessions/00000000-0000-4000-a000-000000000000/claims"
    Then the backend responds with 404

  Scenario: Invalid UUID in session path returns 400
    When a POST is sent to "/sessions/not-a-uuid/claims" with claimText "Test"
    Then the backend responds with 400

  # ---------------------------------------------------------------------------
  # Optional metadata
  # ---------------------------------------------------------------------------

  Scenario: Submit a claim with optional source URL and date
    Given the chat interface is in the idle state
    When the user submits a claim with metadata:
      | field      | value                              |
      | claimText  | Inflation hit 9% in June 2022      |
      | sourceUrl  | https://example.com/article        |
      | sourceDate | 2022-06-15                         |
    Then the backend responds with 202
    And the claim "Inflation hit 9% in June 2022" appears in a user bubble

  # ---------------------------------------------------------------------------
  # Session ID in URL — deep linking
  # ---------------------------------------------------------------------------

  Scenario: Loading a page with a valid session ID in the URL restores the session
    Given a session exists with sessionId {sessionId} and status "active"
    When the user navigates to "/{sessionId}"
    Then a GET request is sent to "/sessions/{sessionId}" returning 200
    And the session state is restored with the submitted claim displayed

  Scenario: Loading a page with a non-existent session ID shows an error
    When the user navigates to "/00000000-0000-4000-a000-000000000000"
    Then a GET request is sent to "/sessions/00000000-0000-4000-a000-000000000000" returning 404
    And an error banner displays "Session not found"

  # ---------------------------------------------------------------------------
  # Network failure during submission
  # ---------------------------------------------------------------------------

  Scenario: Network error during claim submission shows error banner
    Given the chat interface is in the idle state
    And the backend API is unreachable
    When the user submits a claim "Test claim"
    Then an error banner displays "Failed to submit claim"
    And the chat phase transitions to "error"
    And a "Try again" button is visible

  Scenario: Clicking "Try again" after an error resets to idle
    Given the chat phase is "error" with an error banner displayed
    When the user clicks the "Try again" button
    Then the chat phase transitions to "idle"
    And the textarea is enabled and empty
    And the browser URL updates to "/"
