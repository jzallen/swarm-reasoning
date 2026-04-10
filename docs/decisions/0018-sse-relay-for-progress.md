---
status: accepted
date: 2026-04-10
deciders: []
---

# ADR-0018: Server-Sent Events Relay for Real-Time Progress

## Context and Problem Statement

Users submit a claim and wait for results. Agent processing takes 60-120 seconds across 11 agents in three phases (sequential ingestion, parallel fan-out, sequential synthesis). Without real-time updates, the user sees a spinner with no feedback. The system needs to stream user-friendly progress messages from the agent pipeline to the browser.

## Decision Drivers

- Communication is unidirectional: server-to-client only after the initial claim submission
- Native browser `EventSource` API requires no additional client library
- Must be compatible with Cloudflare proxy (with correct response headers)
- Simpler connection management than WebSocket for unidirectional streaming

## Considered Options

1. **Polling** -- Frontend polls `GET /sessions/:id/status` on an interval. Simple to implement but wastes requests during idle periods and adds latency proportional to the polling interval.
2. **WebSocket** -- Bidirectional connection between frontend and backend. Full-duplex capability, but the client never sends messages after claim submission, making bidirectional overhead unnecessary. Requires a WebSocket library on the client and more complex connection lifecycle management.
3. **Server-Sent Events (SSE)** -- Unidirectional server-to-client stream over a single HTTP connection. Native browser `EventSource` API with automatic reconnection. Compatible with HTTP/2 multiplexing.

## Decision Outcome

Chosen option: "Server-Sent Events (SSE)", because the communication is strictly unidirectional after claim submission, the native browser API eliminates client-side dependencies, and SSE's auto-reconnect behavior handles transient network failures without application-level retry logic.

The NestJS backend subscribes to a Redis Stream (`progress:{runId}`) where agents publish user-friendly progress messages. The backend relays these as SSE events to the frontend via `GET /sessions/:id/events`. The frontend renders progress messages in the chat interface as they arrive.

The backend sets `X-Accel-Buffering: no` and `Cache-Control: no-cache` headers on the SSE response to prevent Cloudflare and any upstream proxies from buffering the event stream.

### Consequences

- Good, because the native browser `EventSource` API provides automatic reconnection with no additional client library
- Good, because SSE is compatible with HTTP/2 multiplexing, allowing the progress stream to share a single TCP connection with other API requests
- Bad, because SSE has a browser limit of approximately 6 concurrent connections per domain on HTTP/1.1 (not an issue for this single-session application, and HTTP/2 eliminates the limit)
- Neutral, because if the user leaves and returns mid-run, the backend replays progress messages from the Redis Stream on reconnect, ensuring no messages are lost

## More Information

- ADR-0013: Two Communication Planes (control plane + data plane separation)
- ADR-0014: Three-Service Architecture (backend relays between frontend and agent service)
- ADR-0019: Static HTML Verdict Snapshots (what happens after the SSE stream completes)
