## ADDED Requirements

### Requirement: EventSource hook connects to SSE endpoint and dispatches events

The frontend SHALL provide a `useSSE` custom React hook that wraps the native `EventSource` API. The hook SHALL connect to `GET /sessions/{sessionId}/events`, listen for three event types (`progress`, `verdict`, `close`), parse JSON data, and dispatch typed events to the session state via a callback function.

#### Scenario: SSE connection opens for active session

- **GIVEN** a session ID `{sessionId}` in the `active` state
- **WHEN** the `useSSE` hook is invoked
- **THEN** an `EventSource` is created with URL `/sessions/{sessionId}/events`
- **AND** event listeners are registered for `progress`, `verdict`, and `close` event types

#### Scenario: Progress event dispatched to state

- **GIVEN** an active EventSource connection
- **WHEN** the server sends `event: progress\ndata: {"agent":"entity-extractor","phase":"ingestion","type":"agent-progress","message":"Extracting entities...","timestamp":"2026-04-10T12:00:03Z"}\n\n`
- **THEN** the hook parses the JSON data
- **AND** dispatches a `PROGRESS_EVENT` action to the session state reducer with the parsed `ProgressEvent`

#### Scenario: Verdict event dispatched to state

- **GIVEN** an active EventSource connection
- **WHEN** the server sends `event: verdict\ndata: {"type":"verdict-ready","verdict":{...}}\n\n`
- **THEN** the hook parses the JSON data
- **AND** dispatches a `VERDICT_RECEIVED` action to the session state reducer

#### Scenario: Close event terminates connection

- **GIVEN** an active EventSource connection
- **WHEN** the server sends `event: close\ndata: {"type":"session-frozen"}\n\n`
- **THEN** the hook closes the EventSource
- **AND** dispatches a `SESSION_FROZEN` action to the session state reducer

#### Scenario: Auto-reconnect on transient failure

- **GIVEN** an active EventSource connection
- **WHEN** the connection is lost due to a network error
- **THEN** the browser's native `EventSource` auto-reconnect fires
- **AND** the reconnection request includes the `Last-Event-ID` header with the ID of the last received event
- **AND** missed events are replayed by the server

#### Scenario: Cleanup on unmount

- **GIVEN** an active EventSource connection
- **WHEN** the React component unmounts (e.g., user navigates away)
- **THEN** the EventSource is closed
- **AND** all event listeners are removed

#### Scenario: No connection for non-active sessions

- **GIVEN** a session in state `frozen` or `idle`
- **WHEN** the `useSSE` hook is invoked
- **THEN** no EventSource connection is created

### Requirement: SSE client handles malformed data gracefully

The SSE client SHALL handle malformed JSON data in SSE events without crashing. If a `data` field cannot be parsed as JSON, the event SHALL be logged as a warning and skipped.

#### Scenario: Malformed JSON in SSE data

- **GIVEN** an active EventSource connection
- **WHEN** the server sends `event: progress\ndata: {invalid json}\n\n`
- **THEN** a warning is logged to the console
- **AND** no state dispatch occurs
- **AND** the connection remains open
