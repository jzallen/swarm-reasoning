## ADDED Requirements

### Requirement: Single lifecycle owner
`run_agent_activity` SHALL be the exclusive owner of stream lifecycle events (START, STOP, heartbeat, progress) for all agent types. No handler class SHALL publish START, STOP, heartbeat, or progress events.

#### Scenario: FanoutBase agent lifecycle
- **WHEN** a FanoutBase-derived agent (e.g., source-validator) executes via `run_agent_activity`
- **THEN** exactly one START and one STOP observation SHALL appear in the agent's stream, both published by `run_agent_activity`

#### Scenario: Standalone agent lifecycle
- **WHEN** a standalone agent (e.g., claim-detector) executes via `run_agent_activity`
- **THEN** exactly one START and one STOP observation SHALL appear in the agent's stream, both published by `run_agent_activity`

#### Scenario: LangGraphBase agent lifecycle
- **WHEN** a LangGraphBase-derived agent (e.g., coverage-left) executes via `run_agent_activity`
- **THEN** exactly one START and one STOP observation SHALL appear in the agent's stream, both published by `run_agent_activity`

### Requirement: Heartbeat consolidation
A single heartbeat loop SHALL run in `run_agent_activity`. Handler classes SHALL NOT define or run their own heartbeat loops.

#### Scenario: Heartbeat source
- **WHEN** any agent is executing
- **THEN** `activity.heartbeat()` SHALL be called only from `run_agent_activity`'s heartbeat loop, not from handler code

### Requirement: StreamNotFoundError unification
All stream-not-found errors SHALL use the `StreamNotFoundError` class from `agents/_utils.py`. No other module SHALL define its own `StreamNotFoundError` class.

#### Scenario: Non-retryable stream error
- **WHEN** FanoutBase raises `StreamNotFoundError` because an upstream stream is missing
- **THEN** `run_agent_activity` SHALL catch it as a `NON_RETRYABLE_ERRORS` member and raise `ApplicationError(non_retryable=True)`

#### Scenario: No duplicate error class
- **WHEN** searching the codebase for `class StreamNotFoundError`
- **THEN** exactly one definition SHALL exist, in `agents/_utils.py`

### Requirement: Progress publishing abstraction
`run_agent_activity` SHALL publish progress events through the `ReasoningStream` interface, not by accessing the underlying Redis client directly.

#### Scenario: Progress event via interface
- **WHEN** `run_agent_activity` publishes a progress event
- **THEN** it SHALL call a method on the `ReasoningStream` interface (e.g., `publish_progress()`), not `_stream_client._redis.xadd()`

### Requirement: Shared heartbeat utility
The heartbeat loop implementation SHALL exist in exactly one location (`agents/_utils.py`). All files that previously defined `_heartbeat_loop` SHALL import from `_utils`.

#### Scenario: No duplicate heartbeat implementations
- **WHEN** searching the codebase for `def _heartbeat_loop` or `async def _heartbeat_loop`
- **THEN** exactly one definition SHALL exist, in `agents/_utils.py`
