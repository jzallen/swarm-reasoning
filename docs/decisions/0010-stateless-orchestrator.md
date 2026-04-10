---
status: "superseded by [ADR-0016](0016-temporal-agent-orchestration.md)"
date: 2026-04-08
deciders: []
---

# ADR-0010: Stateless Orchestrator

## Context and Problem Statement

The orchestrator coordinates agent execution and must be able to inspect the current reasoning state of any agent at any point. Two options exist: the orchestrator maintains its own copy of agent state (stateful orchestrator), or the orchestrator reads agent state on demand from the authoritative store (stateless orchestrator).

A stateful orchestrator duplicates data, creates synchronization requirements, and introduces a second source of truth.

## Decision Drivers

- Avoid duplicating agent reasoning state in the orchestrator
- Single source of truth for observations must be the data store, not the orchestrator
- Orchestrator must be recoverable after restart without data loss
- Synchronization overhead between orchestrator and agent state must be eliminated

## Considered Options

1. **Stateful orchestrator** — Maintains its own copy of agent state. Duplicates data, creates synchronization requirements, and introduces a second source of truth.
2. **Stateless orchestrator** — Reads agent state on demand from the authoritative store. Maintains only execution metadata (DAG, connections, run ID, completion register).

## Decision Outcome

Chosen option: "Stateless orchestrator", because it avoids data duplication and synchronization issues. The orchestrator maintains only:

- The DAG of agent execution order and dependencies
- The Temporal workflow execution context
- The current run ID and claim under investigation
- A completion register: which agents have emitted terminal status (`F` or `X`) for their assigned codes in the current run

All other state — observations, intermediate findings, confidence scores — lives in Redis Streams and is read via `XRANGE` queries when the orchestrator needs it. The orchestrator never writes to agent streams directly.

The completion register is ephemeral. If the orchestrator restarts during a run, it can reconstruct completion state by scanning each agent's stream for STOP messages.

### Consequences

- Good, because there is a single source of truth for observations (Redis Streams)
- Good, because the orchestrator can recover after restart by scanning agent streams for STOP messages
- Good, because the orchestrator subscribes to agent streams and receives observations in real time via `XREADGROUP`
- Bad, because each agent must publish observations to its own Redis Stream (`reasoning:{runId}:{agent}`), requiring the orchestrator to consume from all active agent streams for a given run
- Neutral, because the minimum agent contract is: publish START, publish one or more observations, publish STOP with terminal status
- Neutral, because agent Redis Streams are the system's ground truth — Redis persistence configuration (RDB snapshots or AOF) determines durability guarantees

