## Why

The swarm-reasoning system has no implementation code yet — only architecture documents. Every agent, the orchestrator, and the consumer API depend on a shared data layer: typed observations published to Redis Streams. Without this foundation, no agent can publish reasoning and no downstream component can consume it. This slice must be built first because it defines the wire format, type system, and transport interface that all 11 agents and the orchestrator depend on.

## What Changes

- Introduce Python and TypeScript type definitions for the 36 observation codes defined in `docs/domain/obx-code-registry.json`
- Implement the three stream message types (START, OBS, STOP) per `docs/domain/observation-schema-spec.md`
- Implement the `ReasoningStream` abstract interface (ADR-012) with a concrete Redis Streams backend
- Implement epistemic status (P/F/C/X) as a first-class type with transition validation per ADR-005
- Establish stream key format `reasoning:{runId}:{agent}` with XADD/XREAD/XRANGE operations
- Add Redis container configuration to docker-compose with health checks
- Add integration tests for append-only integrity (NFR-009), XRANGE querying (NFR-026), and throughput (NFR-004)

## Capabilities

### New Capabilities
- `observation-types`: Python and TypeScript type definitions for all 36 OBX codes, stream message types (START/OBS/STOP), epistemic status enum, and value type discriminators
- `reasoning-stream`: Abstract `ReasoningStream` interface with Redis Streams implementation — publish, read, query operations with stream key management
- `redis-infrastructure`: Redis container setup, docker-compose service definition, health checks, and connection configuration

### Modified Capabilities

## Impact

- **New packages**: `swarm_reasoning` (Python), `@swarm-reasoning/core` (TypeScript)
- **Infrastructure**: Redis container added to `docs/infrastructure/docker-compose.yml`
- **Dependencies**: `redis-py` (Python), `ioredis` (TypeScript)
- **All downstream slices** (orchestrator, API, all 11 agents) will import these types and use the `ReasoningStream` interface
