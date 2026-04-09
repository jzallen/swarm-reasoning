---
status: "superseded by [ADR-0012](0012-redis-streams-transport.md)"
date: 2026-04-08
deciders: []
---

# ADR-0002: YottaDB for Agent State

## Context and Problem Statement

Each agent bundle requires local storage for the reasoning state it accumulates and reads during a fact-checking run. The storage layer must support: append-only writes of OBX-structured observations, prefix-scan queries over agent-scoped key ranges, ACID transactions for atomic OBX batch writes, and low operational overhead per agent container.

Relational databases (PostgreSQL, SQLite) offer strong query capabilities but impose a fixed schema that must be migrated when new OBX codes are introduced. Document databases (MongoDB) are schemaless but add operational complexity and have no native affinity with the HL7v2 data model.

YottaDB is an open-source MUMPS database. Its native storage model is a hierarchical key-value trie (globals) where subscripts are the keys and leaves are string values. This structure maps directly to the HL7v2 OBX segment: message ID, segment index, and field name become subscripts; field values become leaves. No serialization gap exists between the wire format and storage format.

## Decision Drivers

- Append-only writes of OBX-structured observations
- Prefix-scan queries over agent-scoped key ranges
- ACID transactions for atomic OBX batch writes
- Low operational overhead per agent container
- Zero serialization gap between wire format and storage format

## Considered Options

1. **Relational databases (PostgreSQL, SQLite)** — Strong query capabilities but impose a fixed schema that must be migrated when new OBX codes are introduced.
2. **Document databases (MongoDB)** — Schemaless but add operational complexity and have no native affinity with the HL7v2 data model.
3. **YottaDB** — Hierarchical key-value trie (globals) where subscripts map directly to HL7v2 OBX segment structure. No serialization gap between wire format and storage format.

## Decision Outcome

Chosen option: "YottaDB", because the absence of a serialization gap between HL7v2 wire format and YottaDB storage was the decisive factor. Message ID, segment index, and field name become subscripts; field values become leaves.

### Consequences

- Good, because no serialization gap exists between HL7v2 wire format and YottaDB globals
- Good, because hierarchical key-value trie supports prefix-scan queries natively
- Good, because ACID transactions are supported for atomic batch writes
- Bad, because MUMPS/YottaDB expertise is rare, increasing onboarding friction
- Bad, because each agent bundle requires its own YottaDB instance, contributing to high container count

## More Information

### Supersession Note

ADR-0012 replaces this decision. The zero-serialization-gap argument was circular — YottaDB was chosen because it maps to HL7v2, and HL7v2 was chosen because it maps to YottaDB. With HL7v2 superseded by JSON observations (ADR-0011), YottaDB's primary advantage evaporates. Redis Streams provides append-only log semantics, consumer groups, and streaming delivery with dramatically lower operational overhead (1 container vs. 11).
