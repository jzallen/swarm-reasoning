## ADDED Requirements

### Requirement: Abstract ReasoningStream interface
The system SHALL define an abstract `ReasoningStream` class with async methods: `publish(stream_key, message) -> message_id`, `read(stream_key, last_id) -> list[StreamMessage]`, `read_range(stream_key, start, end) -> list[StreamMessage]`, `read_latest(stream_key) -> StreamMessage | None`. All implementations SHALL accept and return typed `StreamMessage` objects.

#### Scenario: Interface enforces method signatures
- **WHEN** a class inherits ReasoningStream without implementing `publish`
- **THEN** instantiation raises TypeError

### Requirement: Redis Streams implementation
The system SHALL provide `RedisReasoningStream` that implements `ReasoningStream` using Redis Streams. `publish` SHALL use XADD, `read` SHALL use XREAD, `read_range` SHALL use XRANGE. Messages SHALL be serialized as JSON in a `data` field within the Redis stream entry.

#### Scenario: Publish and read round-trip
- **WHEN** a StartMessage is published to `reasoning:run-001:agent-a`
- **AND** the stream is read from the beginning
- **THEN** the returned list contains one StartMessage with matching fields

#### Scenario: Read range filters by ID
- **WHEN** 10 observations are published and read_range is called with start=third_id, end=fifth_id
- **THEN** exactly 3 messages are returned

### Requirement: Stream key format
Stream keys SHALL follow the format `reasoning:{runId}:{agent}`. The system SHALL provide a `stream_key(run_id, agent) -> str` helper function.

#### Scenario: Key generation
- **WHEN** stream_key is called with run_id="claim-42-run-001" and agent="coverage-left"
- **THEN** the result is "reasoning:claim-42-run-001:coverage-left"

### Requirement: Append-only integrity
The Redis implementation SHALL only use XADD for writes. No XDEL, XTRIM, or DEL operations SHALL be exposed on the ReasoningStream interface. Published messages SHALL be immutable.

#### Scenario: No delete operation available
- **WHEN** the ReasoningStream interface is inspected
- **THEN** no method exists for deleting or modifying published messages

#### Scenario: Concurrent writes preserve order
- **WHEN** two agents publish to different streams concurrently
- **THEN** each stream's messages appear in XADD order with monotonically increasing IDs

### Requirement: Observation throughput
The Redis implementation SHALL sustain at least 100 observation publishes per second on the local Docker stack.

#### Scenario: Throughput benchmark
- **WHEN** 1000 observations are published sequentially
- **THEN** the total elapsed time is under 10 seconds

### Requirement: Stream discovery
The system SHALL provide `list_streams(run_id) -> list[str]` that returns all stream keys for a given run by scanning for `reasoning:{runId}:*`.

#### Scenario: Discover all agent streams for a run
- **WHEN** three agents have published to streams for run "run-001"
- **AND** list_streams("run-001") is called
- **THEN** three stream keys are returned
