## Why

The system processes claims across 11 agents in three phases, taking 60-120 seconds per claim. Without real-time progress feedback, users see a blank spinner for the entire duration. The NestJS backend must subscribe to the Redis Streams progress channel and relay agent status updates to the browser via Server-Sent Events. This is the bridge between the data plane (Redis Streams) and the user experience (chat-style progress feed). ADR-0018 selected SSE over WebSocket and polling. This slice implements the backend half of that decision: the SSE endpoint, the Redis subscription adapter, and the reconnection replay logic.

## What Changes

- Add `GET /sessions/:id/events` SSE endpoint in NestJS with `Content-Type: text/event-stream`
- Implement `StreamProgressUseCase` in the application layer that coordinates subscription lifecycle
- Implement `RedisStreamAdapter` in the infrastructure layer that subscribes to `progress:{runId}` via `XREADGROUP BLOCK`
- Define three SSE event types: `progress` (agent updates), `verdict` (final result), `close` (session frozen)
- Support reconnection replay: on reconnect, read missed events from Redis Stream using `Last-Event-ID` header
- Set proxy-bypass headers: `X-Accel-Buffering: no`, `Cache-Control: no-cache` for Cloudflare compatibility
- Connection lifecycle: open on HTTP request, stream events as they arrive, auto-close after `verdict-ready` + `session-frozen` sequence

## Capabilities

### New Capabilities

- `sse-endpoint`: NestJS controller endpoint at `GET /sessions/:id/events` that opens an SSE connection, validates the session exists and is active, and streams typed events (`progress`, `verdict`, `close`) to the browser. Sets required headers for proxy compatibility. Closes after the terminal `close` event.
- `redis-subscription`: Infrastructure adapter that creates a Redis Streams consumer group for the progress stream, reads events via `XREADGROUP BLOCK`, maps raw stream entries to typed `ProgressEvent` objects, and supports replay from a given stream entry ID for reconnection.

### Modified Capabilities

- None. This is a new slice with no modifications to existing capabilities.

## Impact

- **New files**: SSE controller, `StreamProgressUseCase`, `RedisStreamAdapter`, ProgressEvent DTO, SSE event mapper
- **Modified files**: NestJS app module (register controller and providers), Redis module (add consumer group setup)
- **No new containers**: Runs within the existing `backend` service
- **NFR-028**: SSE progress latency < 2000ms from Redis XADD to browser event receipt
