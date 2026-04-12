## Context

The swarm-reasoning project has extensive architecture documentation (13 ADRs, OpenAPI spec, Gherkin features, NFRs) but zero implementation code. This design covers the foundational data layer that every other component depends on: observation types, the stream transport interface, and Redis infrastructure.

Key constraints from ADRs:
- ADR-011: JSON observation schema (not HL7v2)
- ADR-012: Redis Streams transport with abstract interface for Kafka graduation
- ADR-005: Epistemic status (P/F/C/X) carried on every observation
- ADR-003: Append-only log — observations are never overwritten
- ADR-004: Tool layer enforces schema validity; LLMs never construct raw observations

## Goals / Non-Goals

**Goals:**
- Define Python types that are the single source of truth for observation structure
- Provide a `ReasoningStream` abstract interface decoupled from Redis
- Implement a Redis Streams backend that satisfies append-only, queryable, and throughput NFRs
- Establish the project's Python package structure (`swarm_reasoning`)
- Docker Compose Redis service with health checks

**Non-Goals:**
- Kafka backend implementation (ADR-012 defers this to production graduation)
- Temporal workflow implementation (separate slice: temporal-workflow-integration)
- Agent logic or LLM integration
- NestJS backend endpoints

## Decisions

### 1. Python types as source of truth, TypeScript types generated for NestJS
All agents are Python, so Python Pydantic models are the canonical source. TypeScript type definitions are generated from Pydantic JSON Schema for consumption by the NestJS backend (observation deserialization, SSE relay, audit endpoints). The `@swarm-reasoning/core` TypeScript package mirrors the Python models.

**Alternative considered:** Manual TypeScript types maintained separately. Rejected — single source of truth avoids drift.

### 2. Pydantic v2 for observation models
Pydantic provides runtime validation, JSON serialization, and schema generation. The tool layer (ADR-004) uses these models to enforce structural correctness at write time.

**Alternative considered:** dataclasses + manual validation. Rejected — Pydantic gives validation, serialization, and schema export for free.

### 3. Abstract base class for ReasoningStream
```python
class ReasoningStream(ABC):
    async def publish(self, stream_key: str, message: StreamMessage) -> str
    async def read(self, stream_key: str, last_id: str = "0") -> list[StreamMessage]
    async def read_range(self, stream_key: str, start: str = "-", end: str = "+") -> list[StreamMessage]
    async def read_latest(self, stream_key: str) -> StreamMessage | None
```
Redis implementation uses XADD (publish), XREAD (read), XRANGE (read_range).

**Alternative considered:** Protocol-based typing. Rejected — ABC is more explicit about the contract and catches missing methods at class definition time.

### 4. Stream key format: `reasoning:{runId}:{agent}`
Matches the spec. Each agent writes to exactly one stream per run. The orchestrator and synthesizer read across multiple streams using pattern-based key discovery via KEYS or SCAN.

### 5. Epistemic status as validated enum with transition rules
Status transitions are validated: P→F, P→X, F→C, C→C. Invalid transitions raise `InvalidStatusTransition`. This enforces ADR-005 at the type level.

### 6. Package structure
```
src/
  swarm_reasoning/
    __init__.py
    models/
      __init__.py
      observation.py    — OBX codes enum, Observation model, value types
      stream.py         — START/OBS/STOP message models, StreamMessage union
      status.py         — EpistemicStatus enum, transition validation
    stream/
      __init__.py
      base.py           — ReasoningStream ABC
      redis.py          — RedisReasoningStream implementation
    config.py           — Redis connection config
tests/
  integration/
    test_redis_stream.py  — Append-only, XRANGE, throughput tests
  unit/
    test_models.py        — Serialization, validation, status transitions
```

## Risks / Trade-offs

- **[Redis single point of failure]** → Acceptable for dev (ADR-012). Kafka graduation path exists for prod.
- **[KEYS/SCAN for stream discovery]** → O(N) but acceptable at dev scale (<100 streams). Production would use a stream registry.
- **[Pydantic v2 dependency]** → Well-maintained, widely used. Low risk.
- **[TypeScript types must stay in sync]** → Generated from Pydantic JSON Schema; a CI check validates the TypeScript types match the Python models.
