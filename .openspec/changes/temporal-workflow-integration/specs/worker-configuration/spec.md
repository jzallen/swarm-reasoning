## ADDED Requirements

### Requirement: One Temporal worker per agent type
The system SHALL register one Temporal worker per agent type, each polling its own task queue. Task queue naming follows the pattern `agent:{agent-name}`.

#### Scenario: Worker registration
- **WHEN** the agent service starts
- **THEN** 11 workers are created, one per agent type
- **AND** each worker polls its dedicated task queue (e.g., `agent:ingestion-agent`)

#### Scenario: Workflow worker
- **WHEN** the agent service starts
- **THEN** a workflow worker is registered for the `claim-verification` task queue
- **AND** it is capable of executing ClaimVerificationWorkflow

### Requirement: Worker concurrency limits
Each agent worker SHALL have max_concurrent_activities=1 because agents are LLM-bound and stateless. This prevents a single worker from overwhelming LLM API rate limits.

#### Scenario: Concurrent activity limit
- **WHEN** a worker receives a second activity while one is in progress
- **THEN** the second activity waits in the task queue until the first completes

### Requirement: Graceful worker shutdown
Workers SHALL drain in-progress activities before exiting on SIGTERM. Activities that do not complete within a grace period are abandoned and will be retried by Temporal.

#### Scenario: Clean shutdown
- **WHEN** SIGTERM is sent to the agent service
- **THEN** workers stop polling for new activities
- **AND** in-progress activities are given time to complete
- **AND** the process exits after all activities finish or the grace period elapses

### Requirement: Worker entry point as single process
The agent service SHALL run all 11 agent workers and the workflow worker in a single Python process using asyncio. Each worker runs as a concurrent task.

#### Scenario: Single process startup
- **WHEN** `python -m agent_service.worker` is executed
- **THEN** a Temporal client connection is established
- **AND** 12 workers (11 agents + 1 workflow) are started concurrently
- **AND** the process runs until interrupted

#### Scenario: Connection failure at startup
- **WHEN** the Temporal server is unreachable at startup
- **THEN** the worker process logs the connection error and exits with a non-zero code

### Requirement: Worker health check
The agent service SHALL expose a health check endpoint that reports whether the Temporal client connection is active and workers are polling.

#### Scenario: Healthy workers
- **WHEN** the health check is called and all workers are polling
- **THEN** the response indicates healthy status

#### Scenario: Disconnected workers
- **WHEN** the Temporal connection drops
- **THEN** the health check reports unhealthy status

### Requirement: Temporal client configuration via environment
The worker SHALL read Temporal connection details from environment variables: TEMPORAL_ADDRESS (default: localhost:7233), TEMPORAL_NAMESPACE (default: swarm-reasoning).

#### Scenario: Custom Temporal address
- **WHEN** TEMPORAL_ADDRESS is set to `temporal.prod.internal:7233`
- **THEN** the worker connects to that address

#### Scenario: Default address
- **WHEN** TEMPORAL_ADDRESS is not set
- **THEN** the worker connects to `localhost:7233`
