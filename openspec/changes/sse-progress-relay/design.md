## Context

ADR-0018 selected Server-Sent Events for unidirectional server-to-client progress streaming. The NestJS backend subscribes to a Redis Stream (`progress:{runId}`) where agents publish user-friendly progress messages during execution. The backend relays these as typed SSE events to the browser. The frontend uses the native `EventSource` API, which provides automatic reconnection.

Key constraints from architecture docs:
- ADR-0013: Two communication planes -- Temporal control plane + Redis Streams data plane
- ADR-0014: Three-service architecture -- backend is the gateway between frontend and agent service
- ADR-0018: SSE relay with `X-Accel-Buffering: no` and `Cache-Control: no-cache` headers
- ADR-0019: After verdict, session is frozen and SSE connection is closed
- ProgressEvent entity: types are `agent-started`, `agent-progress`, `agent-completed`, `verdict-ready`, `session-frozen`
- SSE event names: `progress`, `verdict`, `close`
- Redis Stream key: `progress:{runId}`
- NFR-028: SSE progress latency < 2000ms from Redis XADD to browser

## Goals / Non-Goals

**Goals:**
- Implement the SSE endpoint with correct Content-Type and proxy-bypass headers
- Subscribe to Redis Streams using consumer groups for reliable delivery
- Map ProgressEvent types to SSE event names
- Support reconnection replay via Last-Event-ID
- Auto-close the connection after the terminal event sequence
- Meet NFR-028 latency target

**Non-Goals:**
- Frontend SSE client implementation (handled by frontend-chat-ui slice)
- ProgressEvent publishing by agents (handled by agent slices)
- WebSocket fallback (rejected by ADR-0018)
- Authentication or authorization on the SSE endpoint
- Rate limiting on the SSE endpoint (Cloudflare handles rate limiting on claim submission)

## Decisions

### 1. NestJS SSE via Observable stream

NestJS natively supports SSE via the `@Sse()` decorator, which returns an `Observable<MessageEvent>`. The controller method returns an RxJS Observable that emits events as they arrive from the Redis subscription. NestJS handles the HTTP response lifecycle, chunked encoding, and connection keep-alive.

**Alternative considered:** Raw `Response` object with manual `res.write()`. Rejected -- loses NestJS lifecycle hooks and requires manual cleanup.

### 2. Redis consumer group per session

Each SSE connection creates a consumer within a shared consumer group for the `progress:{runId}` stream. The consumer group name is `sse-relay` and the consumer name is `sse-{sessionId}-{connectionId}`. This allows multiple simultaneous SSE connections (e.g., user has multiple tabs) to each receive all events independently.

On reconnection, the adapter uses `XREADGROUP` with `>` to get new messages, then replays any missed messages by reading from the entry ID provided in the `Last-Event-ID` header using `XRANGE`.

**Alternative considered:** Single consumer per stream. Rejected -- prevents multiple browser tabs from receiving events.

### 3. Stream entry ID as Last-Event-ID

Each SSE event includes an `id` field set to the Redis Stream entry ID (e.g., `1712736005000-0`). The browser's `EventSource` stores this and sends it as `Last-Event-ID` on reconnect. The adapter uses this ID to replay missed events via `XRANGE(streamKey, lastEventId, '+')`.

**Alternative considered:** Application-level sequence numbers. Rejected -- Redis Stream entry IDs already provide monotonic ordering and are free.

### 4. Connection lifecycle: open -> stream -> close

The SSE connection remains open until one of:
- A `session-frozen` event is received (terminal state)
- The client disconnects
- A server-side timeout (5 minutes of no events)

After emitting the `close` SSE event (mapped from `session-frozen`), the Observable completes, NestJS closes the connection, and the Redis consumer is removed from the group.

### 5. StreamProgressUseCase as the application-layer coordinator

The use case accepts a session ID, validates the session exists and is active (or replays if frozen), creates the Redis subscription, and returns an Observable of SSE events. If the session is already frozen, it replays all events from the stream and completes immediately. If the session is active, it streams events as they arrive.

**Alternative considered:** Put all logic in the controller. Rejected -- violates Clean Architecture (ADR-0015); the controller should only handle HTTP concerns.

### 6. ProgressEvent to SSE event mapping

| ProgressEvent.type | SSE event name | SSE data payload |
|---|---|---|
| `agent-started` | `progress` | `{agent, phase, type, message, timestamp}` |
| `agent-progress` | `progress` | `{agent, phase, type, message, timestamp}` |
| `agent-completed` | `progress` | `{agent, phase, type, message, timestamp}` |
| `verdict-ready` | `verdict` | `{type, verdict: {...}}` |
| `session-frozen` | `close` | `{type: "session-frozen"}` |

The SSE `id` field is always the Redis Stream entry ID.

## Risks / Trade-offs

- **[Consumer group cleanup]** If SSE connections are abandoned (client crashes without disconnect), Redis consumers remain in the group. Mitigation: the cleanup scheduled workflow (from static-html-snapshots slice) deletes the entire stream and consumer group when the session expires.
- **[Blocking XREADGROUP]** Each active SSE connection holds a blocking Redis call. With many concurrent sessions, this could exhaust Redis connections. Mitigation: use a connection pool with a configurable max; portfolio project with low concurrency makes this unlikely.
- **[Cloudflare buffering]** Without `X-Accel-Buffering: no`, Cloudflare may buffer SSE responses. Mitigation: header is set on every SSE response; documented in Cloudflare configuration slice.
- **[Replay after long disconnect]** If a user disconnects for a long period and the stream has been deleted (session expired), replay returns no events. Mitigation: return a `close` event with session status if the stream is gone.
