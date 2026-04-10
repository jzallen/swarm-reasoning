## 1. Project Setup

- [ ] 1.1 Create Python package structure: `src/swarm_reasoning/` with `__init__.py`, `models/`, `stream/`, `config.py`
- [ ] 1.2 Create `pyproject.toml` with dependencies: pydantic>=2.0, redis>=5.0, pytest, pytest-asyncio
- [ ] 1.3 Set up test directory structure: `tests/unit/`, `tests/integration/`

## 2. Observation Types

- [ ] 2.1 Implement `EpistemicStatus` enum (P/F/C/X) with transition validation in `models/status.py`
- [ ] 2.2 Implement `ObservationCode` enum with all 36 codes and metadata from `obx-code-registry.json` in `models/observation.py`
- [ ] 2.3 Implement value type discriminators (ST/NM/CWE/TX) with format validation in `models/observation.py`
- [ ] 2.4 Implement `Observation` Pydantic model with cross-field validation (valueType matches code's registered type) in `models/observation.py`
- [ ] 2.5 Implement `StartMessage`, `ObsMessage`, `StopMessage`, and `StreamMessage` discriminated union in `models/stream.py`
- [ ] 2.6 Write unit tests for all models: valid construction, serialization round-trip, validation errors, status transitions

## 3. ReasoningStream Interface

- [ ] 3.1 Implement `ReasoningStream` ABC in `stream/base.py` with publish, read, read_range, read_latest, list_streams, health
- [ ] 3.2 Implement `stream_key(run_id, agent)` helper function
- [ ] 3.3 Implement `RedisReasoningStream` in `stream/redis.py`: XADD publish, XREAD read, XRANGE read_range
- [ ] 3.4 Implement `list_streams(run_id)` using SCAN for `reasoning:{runId}:*` pattern
- [ ] 3.5 Implement `health()` method with PING/PONG check

## 4. Redis Infrastructure

- [ ] 4.1 Add Redis 7.x service to `docs/infrastructure/docker-compose.yml` with health check and network config
- [ ] 4.2 Implement `RedisConfig` with environment variable loading in `config.py`

## 5. Integration Tests

- [ ] 5.1 Write integration test: publish START/OBS/STOP sequence and read back, verify ordering
- [ ] 5.2 Write integration test: append-only integrity — verify no delete/modify operations
- [ ] 5.3 Write integration test: XRANGE queries with ID-based filtering
- [ ] 5.4 Write integration test: throughput benchmark (1000 observations in <10 seconds)
- [ ] 5.5 Write integration test: stream discovery (list_streams returns all agent streams for a run)
- [ ] 5.6 Write integration test: health check (healthy and unhealthy paths)
