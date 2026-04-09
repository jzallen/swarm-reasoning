---
status: accepted
date: 2026-04-08
deciders: []
---

# ADR-0012: Redis Streams Transport

## Context and Problem Statement

ADR-002 chose YottaDB as per-agent state storage (11 instances). ADR-007 chose Mirth Connect as HL7v2 transport (10 instances). Together they accounted for 21 of the system's 33 containers, all in service of a wire format that has been superseded (ADR-0011).

The system needs a transport and storage layer that provides:
- Append-only log semantics (ADR-0003)
- Streaming delivery with consumer group support
- Per-agent, per-run stream isolation
- Query capability for the synthesizer to read full reasoning logs
- Low operational overhead for local development

## Decision Drivers

- 21 of 33 containers served a now-superseded wire format
- Append-only log semantics must be preserved (ADR-0003)
- Streaming delivery with consumer groups is required
- Per-agent, per-run stream isolation is needed
- Low operational overhead for local development is essential

## Considered Options

1. **Kafka** — Industry-standard event streaming. Durable, replayable, partitioned. Consumer groups, exactly-once semantics, schema registry integration. Operationally heavier than needed for a prototype (JVM, memory requirements), but KRaft mode reduces to 1 container.
2. **Redis Streams** — Append-only log with consumer groups (`XREADGROUP`), blocking reads (`XREAD BLOCK`), range queries (`XRANGE`), and automatic entry ID sequencing. Single container. Low memory overhead. Native support in all target languages (Python, TypeScript). `MAXLEN` for retention control.
3. **PostgreSQL with LISTEN/NOTIFY** — Relational storage with notification channel. Append-only via INSERT-only policy. No native streaming consumer groups. NOTIFY payload limit (8000 bytes) may constrain large observations.

## Decision Outcome

Chosen option: "Redis Streams for development and prototyping", because it provides append-only log semantics, consumer groups, blocking reads, range queries, and automatic entry ID sequencing in a single container with low operational overhead.

The transport layer is accessed through an abstract `ReasoningStream` interface that decouples agents from the specific backend:

```typescript
interface ReasoningStream {
  startStream(runId: string, agent: string, phase: string): Promise<void>;
  publish(observation: Observation): Promise<string>;
  stopStream(runId: string, agent: string, finalStatus: 'F' | 'X'): Promise<void>;

  subscribe(runId: string, agents: string[],
            handler: (msg: StreamMessage) => void): Promise<Subscription>;

  getObservations(runId: string, opts?: {
    agent?: string; code?: string; status?: EpistemicStatus;
  }): Promise<Observation[]>;

  isComplete(runId: string, expectedAgents: string[]): Promise<boolean>;
}
```

A factory function selects the backend based on configuration:

```typescript
function createReasoningStream(config: StreamConfig): ReasoningStream {
  if (config.backend === 'redis') return new RedisReasoningStream(config.redis);
  if (config.backend === 'kafka') return new KafkaReasoningStream(config.kafka);
}
```

### Redis Stream Key Design

```
reasoning:{runId}:{agent}     — per-agent observation stream
reasoning:{runId}:_control    — orchestrator commands (optional)
```

Consumer group: `orchestrator` — the sole consumer of all agent streams, consistent with the hub-and-spoke topology (ADR-0009).

### Graduation Path

Redis Streams serves as the development and prototype backend. Kafka is the production graduation target. The `ReasoningStream` interface makes this a configuration change, not a code change. Key mapping:

| Concern | Redis Streams (dev) | Kafka (prod) |
|---|---|---|
| Stream identity | Key: `reasoning:{runId}:{agent}` | Topic: `agent.{name}`, key: `runId` |
| Subscribe | `XREADGROUP BLOCK` | `KafkaConsumer.subscribe()` |
| Query log | `XRANGE` | Topic replay from offset 0 |
| Retention | `MAXLEN` / `MINID` | Log compaction + retention policy |
| Delivery guarantee | At-least-once (consumer ACK) | Exactly-once (with transactions) |

### Consequences

- Good, because container count drops from 33 to approximately 13: 1 Redis, 10 agents, 1 orchestrator, 1 consumer API
- Good, because the `ReasoningStream` interface is the only component that knows about Redis or Kafka — agents, the orchestrator, and the synthesizer depend on the interface, not the implementation
- Bad, because all agents share a single Redis instance — stream isolation is by key, not by database instance, meaning a Redis failure affects all agents simultaneously
- Bad, because Redis persistence must be configured for durability — `appendonly yes` (AOF) provides crash recovery; for the prototype, RDB snapshots at default intervals are sufficient

## More Information

Supersedes [ADR-0002](0002-yottadb-agent-state.md) and [ADR-0007](0007-mirth-connect-transport.md).
