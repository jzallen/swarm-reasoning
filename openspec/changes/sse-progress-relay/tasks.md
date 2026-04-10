## 1. SSE Controller Setup

- [ ] 1.1 Create `src/interface/controllers/sse-events.controller.ts` with `@Controller('sessions')` and `@Sse(':id/events')` endpoint returning `Observable<MessageEvent>`
- [ ] 1.2 Set response headers: `Content-Type: text/event-stream`, `X-Accel-Buffering: no`, `Cache-Control: no-cache`, `Connection: keep-alive`
- [ ] 1.3 Validate session ID (UUID v4); return 404 if not found, 410 if expired
- [ ] 1.4 If session is `frozen`, replay all events from Redis Stream then complete the Observable
- [ ] 1.5 Register the controller in the NestJS app module

## 2. ProgressEvent DTO and Mapper

- [ ] 2.1 Create `src/domain/entities/progress-event.entity.ts` with fields: `runId`, `agent`, `phase` (ProgressPhase enum), `type` (ProgressType enum), `message`, `timestamp`
- [ ] 2.2 Create `src/domain/enums/progress-phase.enum.ts` (`ingestion`, `fanout`, `synthesis`, `finalization`) and `progress-type.enum.ts` (`agent-started`, `agent-progress`, `agent-completed`, `verdict-ready`, `session-frozen`)
- [ ] 2.3 Create `src/interface/mappers/sse-event.mapper.ts` mapping ProgressType to SSE event names (`progress`, `verdict`, `close`) with `MessageEvent.id` set to Redis Stream entry ID

## 3. StreamProgressUseCase

- [ ] 3.1 Create `src/application/use-cases/stream-progress.use-case.ts` with `execute(sessionId: string, lastEventId?: string): Observable<ProgressEvent>`
- [ ] 3.2 Inject `SessionRepository` to validate session existence and status
- [ ] 3.3 Inject `ProgressStreamPort` interface for Redis subscription
- [ ] 3.4 For active sessions: create subscription, emit events, complete on `session-frozen`
- [ ] 3.5 For frozen sessions: replay all events from stream via `XRANGE('0', '+')`, then complete
- [ ] 3.6 Handle missing stream (session exists but stream cleaned up): emit a single `close` event and complete
- [ ] 3.7 Create `src/application/ports/progress-stream.port.ts` defining the `ProgressStreamPort` interface

## 4. RedisStreamAdapter

- [ ] 4.1 Create `src/infrastructure/adapters/redis-stream.adapter.ts` implementing `ProgressStreamPort`
- [ ] 4.2 On first connection: create consumer group `sse-relay` via `XGROUP CREATE` (handle `BUSYGROUP` if exists); generate unique consumer name `sse-{sessionId}-{uuid()}`
- [ ] 4.3 If `lastEventId` provided, replay missed events via `XRANGE(streamKey, (lastEventId, '+')` before entering blocking read
- [ ] 4.4 Enter blocking read loop: `XREADGROUP GROUP sse-relay {consumer} BLOCK 5000 COUNT 10 STREAMS {streamKey} >`
- [ ] 4.5 Parse each entry into `ProgressEvent`; acknowledge via `XACK`; skip and log malformed entries
- [ ] 4.6 On Observable unsubscribe: remove consumer via `XGROUP DELCONSUMER`
- [ ] 4.7 Handle stream not found: return Observable that completes immediately

## 5. Redis Module Integration

- [ ] 5.1 Create or extend `src/infrastructure/redis/redis-streams.module.ts` to register `RedisStreamAdapter` as `ProgressStreamPort` provider
- [ ] 5.2 Configure Redis connection from `REDIS_URL` environment variable with connection pool

## 6. Connection Lifecycle Management

- [ ] 6.1 Extract `Last-Event-ID` header from SSE request; pass to `StreamProgressUseCase.execute()`
- [ ] 6.2 Implement server-side idle timeout: complete Observable after 5 minutes of no events
- [ ] 6.3 On `session-frozen` event: emit `close` SSE event, then complete Observable
- [ ] 6.4 On client disconnect: detect via NestJS request abort signal, clean up Redis consumer
- [ ] 6.5 On server shutdown: complete all active SSE Observables gracefully

## 7. Error Handling

- [ ] 7.1 Handle Redis connection failure: emit SSE `error` event and retry with exponential backoff
- [ ] 7.2 Handle session deletion during active stream: emit `close` event and complete
- [ ] 7.3 Return proper HTTP error codes: 404 (not found), 410 (expired), 503 (Redis unavailable)

## 8. Unit Tests

- [ ] 8.1 Test `SseEventMapper`: mapping from each ProgressType to correct SSE event name and data format
- [ ] 8.2 Test `StreamProgressUseCase`: active session emits events; frozen session replays and completes; expired session throws
- [ ] 8.3 Test `RedisStreamAdapter.subscribe()`: mock Redis client, verify XGROUP CREATE, XREADGROUP, XACK, XRANGE calls
- [ ] 8.4 Test reconnection: verify XRANGE is called with lastEventId before XREADGROUP loop
- [ ] 8.5 Test idle timeout: verify Observable completes after 5 minutes of no events

## 9. Integration Tests

- [ ] 9.1 Test SSE endpoint with real Redis: publish events, verify they arrive as SSE events
- [ ] 9.2 Test reconnection flow: open, receive, disconnect, reconnect with Last-Event-ID, verify replay
- [ ] 9.3 Test frozen session replay: freeze session, connect, verify all events replayed then close
- [ ] 9.4 Test NFR-028: measure latency from XADD to SSE receipt, assert < 2000ms
