# Covers the user-facing verdict presentation after the swarm completes:
# factuality score, rating badge, narrative, coverage breakdown, blindspot
# warnings, citation table, snapshot view, session expiry, and print action.
# All scenarios describe what the user sees in the browser.

Feature: Verdict Display
  As a user who submitted a claim
  I want to see a clear, annotated verdict with source citations
  So that I can evaluate the claim's truthfulness and trace the evidence

  Background:
    Given the backend API is reachable at "http://localhost:3000"
    And the frontend is loaded at "http://localhost:5173"
    And a session exists with a completed verdict

  # ---------------------------------------------------------------------------
  # Factuality score and rating badge
  # ---------------------------------------------------------------------------

  Scenario Outline: Rating badge reflects the factuality score
    Given the verdict has a factualityScore of <score>
    When the VerdictDisplay renders
    Then the factuality score displays as "<display>"
    And the rating badge shows "<label>" in <colour>

    Examples:
      | score | display | label         | colour |
      | 0.95  | 0.95    | True          | green  |
      | 0.77  | 0.77    | Mostly True   | green  |
      | 0.55  | 0.55    | Half True     | yellow |
      | 0.35  | 0.35    | Mostly False  | orange |
      | 0.18  | 0.18    | False         | red    |
      | 0.04  | 0.04    | Pants on Fire | red    |

  Scenario: Factuality score is displayed to two decimal places
    Given the verdict has a factualityScore of 0.8
    When the VerdictDisplay renders
    Then the factuality score displays as "0.80"

  # ---------------------------------------------------------------------------
  # Narrative
  # ---------------------------------------------------------------------------

  Scenario: Verdict narrative is displayed below the rating
    Given the verdict has narrative "Water boils at 100 degrees Celsius at sea level."
    When the VerdictDisplay renders
    Then the narrative text "Water boils at 100 degrees Celsius at sea level." is visible

  # ---------------------------------------------------------------------------
  # Signal count
  # ---------------------------------------------------------------------------

  Scenario: Signal count describes the evidence basis
    Given the verdict has signalCount 12
    When the VerdictDisplay renders
    Then the text "Based on 12 signals from 11 agents" is visible

  # ---------------------------------------------------------------------------
  # Coverage breakdown
  # ---------------------------------------------------------------------------

  Scenario: Coverage breakdown shows left, centre, and right spectrum cards
    Given the verdict includes coverage observations:
      | agent          | code                   | value             |
      | coverage-left  | COVERAGE_ARTICLE_COUNT | 4                 |
      | coverage-left  | COVERAGE_FRAMING       | POS^Supportive    |
      | coverage-center| COVERAGE_ARTICLE_COUNT | 7                 |
      | coverage-center| COVERAGE_FRAMING       | NEU^Neutral       |
      | coverage-right | COVERAGE_ARTICLE_COUNT | 2                 |
      | coverage-right | COVERAGE_FRAMING       | NEG^Critical      |
    When the VerdictDisplay renders
    Then 3 coverage cards are displayed:
      | spectrum | articleCount | framing    |
      | Left     | 4 article(s) | Supportive |
      | Center   | 7 article(s) | Neutral    |
      | Right    | 2 article(s) | Critical   |

  Scenario: Coverage card shows "Not Covered" when no articles found
    Given coverage-right has no COVERAGE_FRAMING observation
    And coverage-right COVERAGE_ARTICLE_COUNT is 0
    When the VerdictDisplay renders
    Then the Right coverage card displays framing "Not Covered"

  Scenario: Coverage card includes top source link when available
    Given coverage-left has a COVERAGE_TOP_SOURCE_URL observation with value "https://reuters.com/fact-check"
    When the VerdictDisplay renders
    Then the Left coverage card shows a hyperlink "https://reuters.com/fact-check" opening in a new tab

  # ---------------------------------------------------------------------------
  # Blindspot warnings
  # ---------------------------------------------------------------------------

  Scenario: Blindspot warning renders when detected
    Given the verdict includes blindspot observations:
      | agent              | code                         | value                   |
      | blindspot-detector | BLINDSPOT_SCORE              | 0.85                    |
      | blindspot-detector | BLINDSPOT_DIRECTION          | R^Right-leaning gap     |
      | blindspot-detector | CROSS_SPECTRUM_CORROBORATION | TRUE^Corroborated       |
    When the VerdictDisplay renders
    Then a yellow warning banner is visible
    And the warning message contains "Right-leaning gap"
    And the asymmetry score displays as "0.85"

  Scenario: No blindspot warning when blindspot score is low
    Given the verdict has no BLINDSPOT_DIRECTION observations
    When the VerdictDisplay renders
    Then no blindspot warning banner is visible

  # ---------------------------------------------------------------------------
  # Citation table
  # ---------------------------------------------------------------------------

  Scenario: Citation table renders with all columns
    Given the verdict has citations:
      | sourceName | sourceUrl                        | agent           | observationCode  | validationStatus | convergenceCount |
      | NASA       | https://nasa.gov/earth           | domain-evidence | DOMAIN_EVIDENCE  | live             | 5                |
      | Reuters    | https://reuters.com/fact-check   | coverage-center | COVERAGE_TOP_SOURCE_URL | live      | 3                |
      | BlogSpot   | https://blog.example.com/post    | coverage-left   | COVERAGE_TOP_SOURCE_URL | dead      | 1                |
    When the VerdictDisplay renders
    Then the citation table shows 3 rows
    And the columns are: Source, URL, Agent, Code, Status, Cited By

  Scenario: Citations are sorted by convergence count descending
    Given the verdict has citations with convergenceCounts 1, 5, 3
    When the VerdictDisplay renders
    Then the citation table rows are ordered: 5, 3, 1

  Scenario: Citation URL is truncated to 40 characters
    Given a citation has sourceUrl "https://www.very-long-domain-name.example.com/articles/2026/some-long-path"
    When the VerdictDisplay renders
    Then the displayed URL text is truncated to 40 characters
    And the hyperlink href contains the full URL

  Scenario: Validation status indicators are colour-coded
    Given the verdict has citations with validation statuses:
      | validationStatus | expectedColour | expectedLabel  |
      | live             | green          | Live           |
      | dead             | red            | Dead           |
      | redirect         | yellow         | Redirect       |
      | soft-404         | yellow         | Soft 404       |
      | timeout          | yellow         | Timeout        |
      | not-validated    | grey           | Not Validated  |
    When the VerdictDisplay renders
    Then each citation row shows the correct status colour and label

  Scenario: Citation table is hidden when no citations exist
    Given the verdict has an empty citations array
    When the VerdictDisplay renders
    Then no citation table is displayed

  # ---------------------------------------------------------------------------
  # Verdict fetch from API
  # ---------------------------------------------------------------------------

  Scenario: Verdict is fetched after verdict-ready SSE event
    When the SSE stream emits a "verdict" event with type "verdict-ready"
    Then a GET request is sent to "/sessions/{sessionId}/verdict" returning 200
    And the response includes:
      | field            | type    |
      | verdictId        | string  |
      | factualityScore  | number  |
      | ratingLabel      | string  |
      | narrative        | string  |
      | signalCount      | number  |
      | citations        | array   |
      | coverageBreakdown| array   |
      | blindspotWarnings| array   |
      | finalizedAt      | string  |

  Scenario: Verdict endpoint returns 404 before verdict is ready
    Given the session is active but no verdict has been emitted
    When a GET request is sent to "/sessions/{sessionId}/verdict"
    Then the response status is 404

  Scenario: Verdict fetch failure shows error banner
    Given the SSE stream emits a "verdict" event with type "verdict-ready"
    And the GET request to "/sessions/{sessionId}/verdict" fails
    Then an error banner displays "Failed to load verdict"
    And the chat phase transitions to "error"

  # ---------------------------------------------------------------------------
  # Frozen session and snapshot view
  # ---------------------------------------------------------------------------

  Scenario: Frozen session displays snapshot in an iframe
    Given the session status is "frozen"
    And the snapshotUrl is "https://cdn.example.com/snapshots/{sessionId}.html"
    When the user navigates to "/{sessionId}"
    Then the SnapshotView component renders
    And an iframe loads the snapshot URL

  Scenario: Frozen session without snapshot shows fallback message
    Given the session status is "frozen"
    And the snapshotUrl is null
    When the user navigates to "/{sessionId}"
    Then the message "Snapshot is not yet available. The session has been frozen but the snapshot is still being generated." is displayed

  # ---------------------------------------------------------------------------
  # Session expiry
  # ---------------------------------------------------------------------------

  Scenario: Expired session displays retention notice
    Given the session was frozen more than 3 days ago
    And the session status is "expired"
    When the user navigates to "/{sessionId}"
    Then the message "This session has expired. Results are retained for 3 days." is displayed

  # ---------------------------------------------------------------------------
  # Print action
  # ---------------------------------------------------------------------------

  Scenario: Print button triggers browser print dialog
    Given the VerdictDisplay is rendered with a completed verdict
    When the user clicks the "Print" button
    Then the browser print dialog opens
