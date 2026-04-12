## ADDED Requirements

### Requirement: Redis container in docker-compose
The docker-compose configuration SHALL include a Redis 7.x service on the `internal` network with port 6379 exposed to the host. The service SHALL include a health check using `redis-cli ping`.

#### Scenario: Redis starts healthy
- **WHEN** `docker compose up redis` is run
- **THEN** the Redis container reaches healthy status within 30 seconds

#### Scenario: Port accessible from host
- **WHEN** the Redis container is running
- **THEN** `redis-cli -h localhost -p 6379 ping` returns PONG

### Requirement: Connection configuration
The system SHALL provide a `RedisConfig` class with fields: host (default "localhost"), port (default 6379), db (default 0). Configuration SHALL be loadable from environment variables `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`.

#### Scenario: Default configuration
- **WHEN** no environment variables are set
- **THEN** RedisConfig uses localhost:6379/0

#### Scenario: Environment override
- **WHEN** REDIS_HOST=redis and REDIS_PORT=6380 are set
- **THEN** RedisConfig uses redis:6380/0

### Requirement: Connection health check
The `RedisReasoningStream` SHALL provide an `async health() -> bool` method that returns True if the Redis connection is alive (PING/PONG), False otherwise.

#### Scenario: Healthy connection
- **WHEN** Redis is running and health() is called
- **THEN** it returns True

#### Scenario: Unhealthy connection
- **WHEN** Redis is not reachable and health() is called
- **THEN** it returns False without raising an exception
