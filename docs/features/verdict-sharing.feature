# feature: verdict-sharing
# Covers permalink generation, unauthenticated viewing, static HTML
# verdict snapshots with verdict/chat toggle (ADR-019), TTL expiration,
# and CDN caching behaviour.
#
# Compatible with @cucumber/cucumber and jest-cucumber.

Feature: Verdict Sharing

  Background:
    Given a session "SESSION-001" with a completed run and published verdict

  # ---------------------------------------------------------------------------
  # Permalink Generation
  # ---------------------------------------------------------------------------

  Scenario: Completed session produces a shareable permalink
    When the verdict is published for session "SESSION-001"
    Then the Backend API generates a permalink URL for the session
    And the permalink follows the format "/verdicts/{verdictId}"
    And the permalink is included in the verdict response JSON as "permalink"

  Scenario: Permalink is stable across multiple requests
    Given the permalink for session "SESSION-001" has been generated
    When the verdict response is fetched twice
    Then both responses contain the same permalink URL

  Scenario: Permalink is not generated for incomplete runs
    Given session "SESSION-002" has a run in "analyzing" state
    When an operator fetches the session status
    Then the response does not contain a "permalink" field

  # ---------------------------------------------------------------------------
  # Unauthenticated Viewing
  # ---------------------------------------------------------------------------

  Scenario: Anyone can view a verdict via permalink without authentication
    Given the permalink for session "SESSION-001" exists
    When an unauthenticated user visits the permalink URL
    Then the response status is 200
    And the response contains the full verdict content
    And no login or authentication prompt is displayed

  Scenario: Permalink returns 404 after verdict is deleted or expired
    Given the permalink for session "SESSION-001" existed but the snapshot has expired
    When an unauthenticated user visits the permalink URL
    Then the response status is 404
    And the response contains a message indicating the verdict is no longer available

  # ---------------------------------------------------------------------------
  # Static HTML Snapshot (ADR-019)
  # ---------------------------------------------------------------------------

  Scenario: Static HTML snapshot is generated on verdict publication
    When the verdict is published for session "SESSION-001"
    Then a self-contained static HTML file is generated
    And the HTML file is uploaded to S3
    And the HTML file is viewable without JavaScript framework dependencies

  Scenario: Static HTML contains verdict/chat toggle
    Given the static HTML snapshot for session "SESSION-001" has been generated
    When a user views the snapshot
    Then the page displays a verdict summary view by default
    And the page contains a toggle to switch to the chat progress log view
    And the chat view shows agent progress messages in chronological order

  Scenario: Static HTML is print-friendly
    Given the static HTML snapshot for session "SESSION-001" has been generated
    When a user triggers browser print on the snapshot page
    Then the printed output contains the verdict summary
    And the printed output contains source citations
    And no interactive controls appear in the printed output

  Scenario: Static HTML is cached on CDN
    Given the static HTML snapshot has been uploaded to S3
    Then the snapshot is served via CloudFront or Cloudflare CDN
    And subsequent requests for the same permalink are served from CDN cache

  # ---------------------------------------------------------------------------
  # TTL Expiration
  # ---------------------------------------------------------------------------

  Scenario: Static HTML snapshot expires after 3-day TTL
    Given the static HTML snapshot for session "SESSION-001" was generated 3 days ago
    When the S3 lifecycle policy runs
    Then the snapshot object is deleted from S3
    And subsequent requests for the permalink return 404

  Scenario: TTL is set at upload time
    When the static HTML snapshot is uploaded to S3
    Then the S3 object has an expiration policy of 3 days
    And the Cache-Control header includes a max-age consistent with the TTL
