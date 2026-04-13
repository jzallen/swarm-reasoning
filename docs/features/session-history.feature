# feature: session-history
# Covers listing past claims, navigating to previous sessions, and
# starting new sessions from the chat-based frontend.
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Session History

  Background:
    Given the frontend is loaded in a browser
    And the Backend API is reachable

  # ---------------------------------------------------------------------------
  # Past Claims List
  # ---------------------------------------------------------------------------

  Scenario: User sees a list of past claims
    Given the user has previously submitted 3 claims across separate sessions
    When the user navigates to the session history view
    Then the history displays 3 entries
    And each entry shows the claim text, verdict label, and submission date
    And entries are ordered by submission date descending

  Scenario: Empty history shows an informative message
    Given the user has no previous sessions
    When the user navigates to the session history view
    Then the view displays a message indicating no claims have been submitted
    And the view contains a prompt to submit a new claim

  Scenario: In-progress sessions appear in history with pending status
    Given the user has one completed session and one session in "analyzing" state
    When the user navigates to the session history view
    Then the completed session shows its verdict label
    And the in-progress session shows status "analyzing"
    And the in-progress session does not display a verdict label

  Scenario: Cancelled sessions appear in history with cancelled status
    Given the user has a session whose run was cancelled due to low check-worthiness
    When the user navigates to the session history view
    Then the cancelled session shows status "cancelled"
    And the cancelled session does not display a verdict label

  # ---------------------------------------------------------------------------
  # Navigate to Previous Session
  # ---------------------------------------------------------------------------

  Scenario: User can open a completed session from history
    Given the session history contains a completed session "SESSION-001"
    When the user clicks on session "SESSION-001"
    Then the chat view loads the claim text, agent progress messages, and verdict for "SESSION-001"
    And the verdict summary is displayed

  Scenario: User can open an in-progress session from history
    Given the session history contains a session "SESSION-002" in "analyzing" state
    When the user clicks on session "SESSION-002"
    Then the chat view loads the claim text and agent progress messages received so far
    And the SSE connection resumes delivering new progress events for "SESSION-002"

  Scenario: Navigating to a session preserves the URL for bookmarking
    When the user navigates to session "SESSION-001" from history
    Then the browser URL updates to include the session identifier
    And refreshing the page reloads the same session

  # ---------------------------------------------------------------------------
  # Start New Session
  # ---------------------------------------------------------------------------

  Scenario: User starts a new session from the history view
    Given the user is viewing the session history
    When the user clicks the "New Claim" button
    Then the view transitions to an empty chat input
    And the session history is no longer visible
    And the user can type and submit a new claim

  Scenario: User starts a new session from a completed session view
    Given the user is viewing the verdict for session "SESSION-001"
    When the user clicks the "New Claim" button
    Then a new empty chat session begins
    And session "SESSION-001" remains accessible in the history

  Scenario: Submitting a new claim creates a new session entry in history
    Given the user starts a new session and submits a claim
    When the user navigates back to the session history
    Then the new session appears at the top of the history list
