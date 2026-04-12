## ADDED Requirements

### Requirement: SSE endpoint streams typed events to the browser

The NestJS backend SHALL expose `GET /sessions/:id/events` as a Server-Sent Events endpoint. The response SHALL have `Content-Type: text/event-stream`, `X-Accel-Buffering: no`, `Cache-Control: no-cache`, and `Connection: keep-alive` headers. The endpoint SHALL emit three SSE event types: `progress` (agent status updates), `verdict` (final verdict payload), and `close` (session frozen signal). Each SSE event SHALL include an `id` field set to the Redis Stream entry ID for reconnection support.

#### Scenario: Successful SSE connection for active session

- **GIVEN** a session with ID `{sessionId}` exists in status `active`
- **WHEN** a client sends `GET /sessions/{sessionId}/events`
- **THEN** the response status is 200
- **AND** the `Content-Type` header is `text/event-stream`
- **AND** the `X-Accel-Buffering` header is `no`
- **AND** the `Cache-Control` header is `no-cache`

#### Scenario: SSE emits progress events from agents

- **GIVEN** an active SSE connection for session `{sessionId}`
- **WHEN** the ingestion-agent publishes a progress event `{"agent":"ingestion-agent","phase":"ingestion","type":"agent-started","message":"Analyzing claim..."}` to the `progress:{runId}` Redis Stream
- **THEN** the SSE endpoint emits an event with `event: progress` and `data` containing the agent, phase, type, message, and timestamp fields
- **AND** the event has an `id` field matching the Redis Stream entry ID

#### Scenario: SSE emits verdict event

- **GIVEN** an active SSE connection for session `{sessionId}`
- **WHEN** the backend publishes a `verdict-ready` progress event with the verdict payload
- **THEN** the SSE endpoint emits an event with `event: verdict` and `data` containing the verdict object

#### Scenario: SSE connection closes after session-frozen event

- **GIVEN** an active SSE connection for session `{sessionId}`
- **WHEN** the backend publishes a `session-frozen` progress event
- **THEN** the SSE endpoint emits an event with `event: close` and `data: {"type":"session-frozen"}`
- **AND** the SSE stream completes and the HTTP connection is closed

#### Scenario: SSE endpoint returns 404 for unknown session

- **GIVEN** no session exists with ID `{sessionId}`
- **WHEN** a client sends `GET /sessions/{sessionId}/events`
- **THEN** the response status is 404

#### Scenario: SSE endpoint returns 410 for expired session

- **GIVEN** a session with ID `{sessionId}` exists in status `expired`
- **WHEN** a client sends `GET /sessions/{sessionId}/events`
- **THEN** the response status is 410

#### Scenario: SSE replays all events for frozen session

- **GIVEN** a session with ID `{sessionId}` exists in status `frozen`
- **AND** the `progress:{runId}` Redis Stream contains 15 events
- **WHEN** a client sends `GET /sessions/{sessionId}/events`
- **THEN** all 15 events are emitted as SSE events in order
- **AND** the stream completes after the last event

### Requirement: SSE reconnection replays missed events via Last-Event-ID

When a client reconnects after a disconnection, the browser's `EventSource` sends the `Last-Event-ID` header with the ID of the last received event. The SSE endpoint SHALL replay all events published after that ID before resuming the live stream.

#### Scenario: Reconnection replays missed events

- **GIVEN** a client received SSE events up to Redis entry ID `1712736005000-3`
- **AND** events `1712736005000-4` through `1712736005000-7` were published while the client was disconnected
- **WHEN** the client reconnects with `Last-Event-ID: 1712736005000-3`
- **THEN** events `1712736005000-4` through `1712736005000-7` are emitted first
- **AND** subsequent live events are emitted as they arrive

#### Scenario: Reconnection with no missed events

- **GIVEN** a client received SSE events up to Redis entry ID `1712736005000-7`
- **AND** no new events were published during the disconnection
- **WHEN** the client reconnects with `Last-Event-ID: 1712736005000-7`
- **THEN** no replay events are emitted
- **AND** the connection enters live streaming mode

### Requirement: SSE progress latency under 2000ms (NFR-028)

The time elapsed from an agent publishing a progress event via `XADD` to the `progress:{runId}` Redis Stream until the browser receives the corresponding SSE event SHALL be less than 2000 milliseconds under normal operating conditions.

#### Scenario: Latency measurement

- **GIVEN** the backend SSE endpoint is connected for an active session
- **WHEN** an agent publishes a progress event via `XADD` at time T1
- **AND** the browser receives the SSE event at time T2
- **THEN** T2 - T1 < 2000ms

### Requirement: SSE connection lifecycle management

The SSE connection SHALL be managed by the `StreamProgressUseCase` in the application layer, adhering to NestJS Clean Architecture (ADR-0015). The controller SHALL handle only HTTP concerns. The use case SHALL coordinate session validation, Redis subscription, and event mapping.

#### Scenario: Server-side idle timeout

- **GIVEN** an active SSE connection
- **WHEN** no events arrive for 5 minutes
- **THEN** the connection is closed by the server

#### Scenario: Client disconnect cleanup

- **GIVEN** an active SSE connection with a Redis consumer `sse-{sessionId}-{connectionId}`
- **WHEN** the client disconnects
- **THEN** the Redis consumer is removed from the consumer group via `XGROUP DELCONSUMER`
