# Covers real-time progress visibility through the SSE event stream:
# connection lifecycle, progress bubble rendering, phase badges, reconnection
# handling, and error timeout behaviour.  All scenarios describe what the user
# observes in the browser, not internal Redis or Temporal mechanics.

Feature: Progress Tracking
  As a user who has submitted a claim
  I want to see real-time progress from each agent
  So that I understand how my claim is being evaluated

  Background:
    Given the backend API is reachable at "http://localhost:3000"
    And the frontend is loaded at "http://localhost:5173"
    And the user has submitted a claim and the session is in the "active" phase

  # ---------------------------------------------------------------------------
  # SSE connection establishment
  # ---------------------------------------------------------------------------

  Scenario: SSE connection opens when session becomes active
    When the claim submission returns 202 and the phase transitions to "active"
    Then an EventSource connection is opened to "/sessions/{sessionId}/events"
    And a system message "Connecting to agents..." appears in the progress stream

  Scenario: SSE connection is not opened while phase is idle
    Given the chat interface is in the idle state
    Then no EventSource connection exists

  # ---------------------------------------------------------------------------
  # Progress event rendering
  # ---------------------------------------------------------------------------

  Scenario: Progress events render as timestamped bubbles
    When the SSE stream emits a "progress" event with data:
      | field     | value                                |
      | runId     | claim-4821-run-001                   |
      | agent     | ingestion-agent                      |
      | phase     | ingestion                            |
      | type      | agent-started                        |
      | message   | Extracting entities from claim text   |
      | timestamp | 2026-04-13T12:00:01Z                 |
    Then a progress bubble appears with:
      | element   | value                                |
      | agent     | ingestion-agent                      |
      | badge     | Ingestion                            |
      | message   | Extracting entities from claim text   |
      | timestamp | 12:00:01                             |

  Scenario: Multiple progress events appear in chronological order
    When the SSE stream emits progress events from three agents:
      | agent              | phase     | type             | message                          | timestamp                |
      | ingestion-agent    | ingestion | agent-started    | Parsing claim text               | 2026-04-13T12:00:00Z     |
      | claim-detector     | ingestion | agent-started    | Scoring check-worthiness         | 2026-04-13T12:00:02Z     |
      | entity-extractor   | ingestion | agent-completed  | Extracted 3 entities             | 2026-04-13T12:00:04Z     |
    Then 3 progress bubbles appear in the stream
    And they are ordered by timestamp ascending

  Scenario: Phase badges are colour-coded by execution phase
    When progress events arrive for each phase:
      | agent            | phase          |
      | ingestion-agent  | ingestion      |
      | coverage-left    | fanout         |
      | synthesizer      | synthesis      |
      | synthesizer      | finalization   |
    Then the phase badges display:
      | phase         | label          |
      | ingestion     | Ingestion      |
      | fanout        | Fanout         |
      | synthesis     | Synthesis      |
      | finalization  | Finalization   |

  Scenario: Agent lifecycle events are styled distinctly from progress events
    When the SSE stream emits an "agent-started" event for "coverage-left"
    And the SSE stream emits an "agent-progress" event for "coverage-left"
    And the SSE stream emits an "agent-completed" event for "coverage-left"
    Then the "agent-started" and "agent-completed" bubbles use lifecycle styling
    And the "agent-progress" bubble uses standard progress styling

  # ---------------------------------------------------------------------------
  # Three-phase execution visibility
  # ---------------------------------------------------------------------------

  Scenario: Ingestion phase events precede fan-out events
    When progress events arrive in execution order
    Then all "ingestion" phase events appear before any "fanout" phase events

  Scenario: Fan-out phase shows parallel agent activity
    When the fan-out phase is active
    Then progress events arrive from multiple agents concurrently:
      | agent              |
      | claimreview-matcher |
      | coverage-left       |
      | coverage-center     |
      | coverage-right      |
      | domain-evidence     |
    And the events interleave by timestamp

  Scenario: Synthesis phase events follow fan-out completion
    When all fan-out agents have emitted "agent-completed"
    Then progress events from "blindspot-detector" and "synthesizer" appear
    And they carry the "synthesis" phase badge

  # ---------------------------------------------------------------------------
  # Verdict-ready and session-frozen SSE events
  # ---------------------------------------------------------------------------

  Scenario: Verdict-ready event triggers verdict fetch
    When the SSE stream emits a "verdict" event with data:
      | field | value         |
      | type  | verdict-ready |
    Then a GET request is sent to "/sessions/{sessionId}/verdict"
    And the chat phase transitions to "verdict"
    And the VerdictDisplay component renders

  Scenario: Session-frozen event transitions to frozen phase
    When the SSE stream emits a "close" event with data:
      | field       | value                                       |
      | type        | session-frozen                               |
      | snapshotUrl | https://cdn.example.com/snapshots/{sessionId}.html |
    Then the chat phase transitions to "frozen"
    And the SSE connection is closed
    And the SnapshotView component renders with the snapshot URL

  # ---------------------------------------------------------------------------
  # Reconnection and resilience
  # ---------------------------------------------------------------------------

  Scenario: User returns to active session via URL and SSE reconnects
    Given the user previously submitted a claim in session {sessionId}
    And the session status is "active"
    When the user navigates to "/{sessionId}"
    Then a GET request to "/sessions/{sessionId}" returns status "active"
    And an EventSource connection is opened to "/sessions/{sessionId}/events"
    And a banner displays "Reconnected — earlier messages not shown"

  Scenario: SSE connection loss within 30 seconds does not show error
    Given the SSE stream is connected
    When the EventSource fires an error event
    And the readyState is not CLOSED
    Then no error banner is displayed
    And the browser attempts automatic reconnection

  Scenario: SSE connection closed by server within error timeout recovers
    Given the SSE stream is connected
    When the EventSource fires an error event with readyState CLOSED
    Then an error banner displays "Lost connection to server"
    And the chat phase transitions to "error"

  Scenario: SSE reconnection fails after 30-second timeout
    Given the SSE stream is connected
    When the EventSource fires an error event
    And 30 seconds elapse without successful reconnection
    Then an error banner displays "Unable to reconnect to server after 30 seconds"
    And the SSE connection is closed
    And the chat phase transitions to "error"

  # ---------------------------------------------------------------------------
  # Malformed event handling
  # ---------------------------------------------------------------------------

  Scenario: Malformed SSE JSON is silently ignored
    When the SSE stream emits a "progress" event with invalid JSON "{bad"
    Then no progress bubble is added to the stream
    And no error banner is displayed
    And a warning is logged to the browser console

  # ---------------------------------------------------------------------------
  # SSE latency requirement
  # ---------------------------------------------------------------------------

  Scenario: Progress events arrive within acceptable latency
    When an agent publishes an observation to Redis at time T
    Then the corresponding SSE progress event reaches the browser within 2000ms of T
