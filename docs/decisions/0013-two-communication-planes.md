---
status: accepted
date: 2026-04-08
deciders: []
---

# ADR-0013: Two Communication Planes

## Context and Problem Statement

The system uses two distinct communication mechanisms: Temporal for control (orchestrator dispatching agent workflow activities) and Redis Streams for data (agents publishing observations).

## Decision Outcome

The two-plane architecture is retained:

**Control plane -- Temporal**
- Orchestrator workflow dispatches agent activities
- Agent activities receive task parameters and return results
- Durable execution with automatic retry and timeout handling
- Workflow defines the DAG of agent execution order and dependencies

**Data plane -- Redis Streams**
- Agent to Stream: observation publication (START, OBS, STOP)
- Orchestrator from Stream: observation consumption via consumer groups
- Asynchronous append/subscribe pattern
- Agents write to their own stream; orchestrator reads all streams

The planes fail independently. If Temporal is down, the orchestrator cannot dispatch new agent activities, but agents with in-flight work can continue publishing observations to Redis Streams. If Redis is down, agents cannot publish observations, but Temporal activity dispatch still functions. The orchestrator can detect plane failures independently and report degraded status.

### Consequences

- Good, because the planes fail independently, providing partial availability during component failures
- Good, because the orchestrator can detect and report degraded status per plane
- Bad, because agents must be resilient to Redis unavailability: buffer observations locally and retry publication when Redis recovers
- Neutral, because observation delivery is not confirmed via Temporal -- the orchestrator detects completion by reading STOP messages from Redis Streams, not by receiving Temporal activity results
- Neutral, because health checks must cover both Temporal connectivity (workflow service) and Redis connectivity (single instance)
