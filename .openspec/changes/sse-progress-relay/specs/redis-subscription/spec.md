## ADDED Requirements

### Requirement: RedisStreamAdapter subscribes to progress stream via consumer groups

The `RedisStreamAdapter` SHALL implement the `ProgressStreamPort` interface and subscribe to Redis Streams using `XREADGROUP`. The adapter SHALL create a consumer group named `sse-relay` on the `progress:{runId}` stream. Each SSE connection SHALL have a unique consumer name (`sse-{sessionId}-{uuid}`). Messages SHALL be acknowledged via `XACK` after processing.

#### Scenario: Consumer group creation on first subscription

- **GIVEN** no consumer group `sse-relay` exists on stream `progress:{runId}`
- **WHEN** the `RedisStreamAdapter` subscribes to the stream
- **THEN** a consumer group `sse-relay` is created via `XGROUP CREATE progress:{runId} sse-relay 0 MKSTREAM`
- **AND** a consumer `sse-{sessionId}-{uuid}` is registered

#### Scenario: Consumer group already exists

- **GIVEN** consumer group `sse-relay` already exists on stream `progress:{runId}`
- **WHEN** the `RedisStreamAdapter` subscribes to the stream
- **THEN** the `BUSYGROUP` error from `XGROUP CREATE` is caught and ignored
- **AND** a new consumer is registered in the existing group

#### Scenario: Blocking read loop

- **GIVEN** a subscription is active for stream `progress:{runId}`
- **WHEN** `XREADGROUP GROUP sse-relay {consumer} BLOCK 5000 COUNT 10 STREAMS progress:{runId} >` returns entries
- **THEN** each entry is parsed into a `ProgressEvent` object
- **AND** each entry is acknowledged via `XACK progress:{runId} sse-relay {entryId}`

#### Scenario: Replay from entry ID

- **GIVEN** a subscription with `lastEventId` = `1712736005000-3`
- **WHEN** the adapter starts the subscription
- **THEN** it first executes `XRANGE progress:{runId} (1712736005000-3 +` to read all entries after the given ID
- **AND** emits those entries before entering the blocking read loop

#### Scenario: Consumer cleanup on disconnect

- **GIVEN** a consumer `sse-abc123-uuid456` is registered in group `sse-relay`
- **WHEN** the subscription Observable is unsubscribed
- **THEN** the adapter calls `XGROUP DELCONSUMER progress:{runId} sse-relay sse-abc123-uuid456`

### Requirement: Stream entry parsing to ProgressEvent

Each Redis Stream entry SHALL be parsed into a typed `ProgressEvent` object. The adapter SHALL validate that required fields (`runId`, `agent`, `phase`, `type`, `message`, `timestamp`) are present. Malformed entries SHALL be logged as warnings and skipped without breaking the subscription.

#### Scenario: Valid stream entry parsed

- **GIVEN** a Redis Stream entry with fields: `runId=claim-4821-run-003`, `agent=coverage-left`, `phase=fanout`, `type=agent-progress`, `message=Searching left-leaning sources...`, `timestamp=2026-04-10T12:00:05Z`
- **WHEN** the entry is parsed
- **THEN** a `ProgressEvent` object is returned with all fields correctly typed

#### Scenario: Malformed entry is skipped

- **GIVEN** a Redis Stream entry missing the `agent` field
- **WHEN** the entry is parsed
- **THEN** a warning is logged with the entry ID and stream key
- **AND** the entry is skipped (not emitted to the Observable)
- **AND** the entry is still acknowledged via `XACK` to prevent redelivery

### Requirement: Observable lifecycle matches SSE connection

The `subscribe()` method SHALL return an RxJS `Observable<{entryId: string, event: ProgressEvent}>`. The Observable SHALL emit events as they are read from Redis. The Observable SHALL complete when a `session-frozen` event is read. The Observable SHALL clean up Redis resources (consumer removal) on both completion and error.

#### Scenario: Observable completes on terminal event

- **GIVEN** an active subscription Observable
- **WHEN** a stream entry with `type=session-frozen` is read
- **THEN** the event is emitted to the Observable
- **AND** the Observable completes (no further events)

#### Scenario: Observable error on Redis connection loss

- **GIVEN** an active subscription Observable
- **WHEN** the Redis connection is lost
- **THEN** the Observable emits an error
- **AND** the consumer is removed from the group (best-effort)

#### Scenario: Stream does not exist

- **GIVEN** a subscription request for stream `progress:nonexistent-run`
- **WHEN** the adapter attempts to subscribe
- **THEN** the Observable completes immediately without emitting any events
