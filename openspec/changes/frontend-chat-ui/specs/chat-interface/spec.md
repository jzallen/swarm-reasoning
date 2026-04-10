## ADDED Requirements

### Requirement: Chat interface for claim submission and progress display

The frontend SHALL render a chat-style interface as the primary user interaction surface. The interface SHALL consist of a scrolling message area and a claim input form. Users submit a claim via the text input, which triggers session creation and claim processing. Progress messages from agents are rendered as chat bubbles in real-time.

#### Scenario: Landing page renders claim input

- **GIVEN** no session ID is present in the URL path
- **WHEN** the frontend loads
- **THEN** a text input area with placeholder "Enter a claim to fact-check..." is displayed
- **AND** a submit button labeled "Check Claim" is displayed
- **AND** the message area is empty

#### Scenario: Claim submission creates session and updates URL

- **GIVEN** the user has typed a claim in the text input
- **WHEN** the user clicks the submit button
- **THEN** `POST /sessions` is called to create a new session
- **AND** `POST /sessions/{sessionId}/claims` is called with the claim text
- **AND** the browser URL is updated to `/{sessionId}` via `pushState`
- **AND** the submitted claim appears as the first message in the chat area (right-aligned, user-style bubble)

#### Scenario: Input is disabled after claim submission

- **GIVEN** a claim has been submitted for the current session
- **WHEN** the user views the chat interface
- **THEN** the text input is disabled
- **AND** the submit button is disabled
- **AND** a visual indicator shows that processing is in progress

#### Scenario: Connecting placeholder shown before first event

- **GIVEN** a claim has been submitted
- **AND** no SSE events have arrived yet
- **WHEN** the user views the chat area
- **THEN** a placeholder message "Connecting to agents..." is displayed below the submitted claim

#### Scenario: Progress events render as chat bubbles

- **GIVEN** the SSE connection is active
- **WHEN** a `progress` event arrives with `agent=coverage-left`, `phase=fanout`, `message=Searching left-leaning sources...`
- **THEN** a chat bubble appears in the message area with:
  - Agent name "coverage-left" as a bold label
  - Phase badge "fanout" with colored background
  - Message text "Searching left-leaning sources..."
  - Timestamp in the corner

#### Scenario: Chat auto-scrolls to latest message

- **GIVEN** the message area contains progress messages
- **WHEN** a new progress event arrives
- **THEN** the message area auto-scrolls to show the newest message at the bottom

#### Scenario: Page load with existing session ID in URL

- **GIVEN** the URL path is `/{sessionId}` where `{sessionId}` is a valid UUID
- **WHEN** the frontend loads
- **THEN** `GET /sessions/{sessionId}` is called to fetch the session status
- **AND** if the session is `active`, the SSE connection is opened and the chat interface shows progress
- **AND** if the session is `frozen`, the snapshot view is displayed instead

### Requirement: Progress bubble component renders agent messages with visual styling

Each progress event SHALL be rendered as a chat bubble with the agent name, phase badge, message text, and timestamp. Agent lifecycle events (`agent-started`, `agent-completed`) SHALL be visually distinguished from progress updates.

#### Scenario: Phase badge colors

- **GIVEN** a progress event with `phase=ingestion`
- **WHEN** the bubble is rendered
- **THEN** the phase badge has a blue background

- **GIVEN** a progress event with `phase=fanout`
- **WHEN** the bubble is rendered
- **THEN** the phase badge has a green background

- **GIVEN** a progress event with `phase=synthesis`
- **WHEN** the bubble is rendered
- **THEN** the phase badge has a purple background

#### Scenario: Agent lifecycle events styled differently

- **GIVEN** a progress event with `type=agent-started`
- **WHEN** the bubble is rendered
- **THEN** the message text is displayed in italic with a lighter color than `agent-progress` events

### Requirement: Responsive layout works on desktop and mobile

The chat interface SHALL be responsive. On desktop (viewport > 1024px), the chat container is centered with a maximum width of 720px. On mobile (viewport < 640px), the chat container fills the full width with appropriate padding.

#### Scenario: Desktop layout

- **GIVEN** a viewport width of 1200px
- **WHEN** the chat interface renders
- **THEN** the chat container is centered with max-width 720px

#### Scenario: Mobile layout

- **GIVEN** a viewport width of 375px
- **WHEN** the chat interface renders
- **THEN** the chat container fills the full width with 16px horizontal padding
