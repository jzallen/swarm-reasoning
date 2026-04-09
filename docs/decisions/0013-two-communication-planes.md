---
status: accepted
date: 2026-04-08
deciders: []
---

# ADR-0013: Two Communication Planes

## Context and Problem Statement

The system uses two distinct communication mechanisms: MCP for control (orchestrator issuing commands to agents) and Redis Streams for data (agents publishing observations). This separation was present in the original architecture (MCP + Mirth/HL7v2) and is preserved in the new stack.

## Decision Outcome

The two-plane architecture is retained:

**Control plane -- MCP (Model Context Protocol)**
- Orchestrator to Agent: task assignment, configuration, queries
- Agent to Orchestrator: tool call results, status responses
- Synchronous request/response pattern
- Hub-and-spoke topology (ADR-0009)

**Data plane -- Redis Streams**
- Agent to Stream: observation publication (START, OBS, STOP)
- Orchestrator from Stream: observation consumption via consumer groups
- Asynchronous append/subscribe pattern
- Agents write to their own stream; orchestrator reads all streams

The planes fail independently. If MCP is down, the orchestrator cannot issue new commands, but agents can continue publishing observations to Redis Streams. If Redis is down, agents cannot publish observations, but MCP commands still function. The orchestrator can detect plane failures independently and report degraded status.

### Consequences

- Good, because the planes fail independently, providing partial availability during component failures
- Good, because the orchestrator can detect and report degraded status per plane
- Bad, because agents must be resilient to Redis unavailability: buffer observations locally and retry publication when Redis recovers
- Neutral, because observation delivery is not confirmed via MCP -- the orchestrator detects completion by reading STOP messages from Redis Streams, not by receiving MCP responses
- Neutral, because health checks must cover both MCP connectivity (per-agent) and Redis connectivity (single instance)
