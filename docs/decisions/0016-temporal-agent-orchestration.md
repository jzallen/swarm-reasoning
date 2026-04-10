---
status: accepted
date: 2026-04-10
deciders: []
---

# ADR-0016: Temporal.io for Agent Orchestration

## Context and Problem Statement

The orchestrator must dispatch 11 agents across three phases (sequential ingestion, parallel fan-out, sequential synthesis), handle long-running LLM calls, retry failed agent activities, and survive process restarts without losing progress. Previously, MCP was used as the control plane (ADR-0009) with a stateless orchestrator that reconstructed state from Redis Streams (ADR-0010). This approach works but requires custom recovery logic, has no built-in retry or timeout mechanisms, and represents a single point of failure.

## Decision Drivers

- Agent workflows run for minutes; the orchestrator must survive process crashes mid-execution
- Transient LLM API failures (rate limits, timeouts) require automatic retry with backoff
- The three-phase execution pattern (sequential -> parallel fan-out -> sequential) must be expressible in the orchestration framework
- Workflow visibility and debugging tooling reduce operational burden
- The Redis Streams data plane (ADR-0012) must remain unchanged

## Considered Options

1. **Keep MCP control plane** -- Retain hub-and-spoke MCP topology (ADR-0009) with stateless orchestrator recovery via Redis Streams scanning (ADR-0010). Works but requires custom recovery logic, no built-in retry/timeout, and MCP hub is a single point of failure.
2. **Temporal.io** -- Durable execution platform. Workflows survive process crashes via event history replay. Built-in retry policies, activity timeouts, workflow visibility UI. Scales to multiple workers.
3. **Custom queue-based orchestration** -- SQS or Redis queues with custom consumer logic. Lightweight but requires building retry, timeout, and state management from scratch.

## Decision Outcome

Chosen option: "Temporal.io", because durable execution eliminates the need for manual orchestrator recovery (ADR-0010 state reconstruction), built-in retry policies handle transient LLM API failures, activity timeouts bound agent execution, and the Temporal UI provides workflow visibility for debugging.

**Workflow structure**:
- The orchestrator is a Temporal workflow (`ClaimVerificationWorkflow`)
- Each agent type is a Temporal activity executed by a dedicated worker in the Python agent service
- Phase 1 (sequential): ingestion-agent, claim-detector, entity-extractor activities run in sequence
- Phase 2 (parallel fan-out): claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence, source-validator activities run concurrently
- Phase 3 (sequential): blindspot-detector, synthesizer activities run in sequence
- Agents still publish observations to Redis Streams (data plane unchanged)
- The orchestrator workflow monitors agent streams for STOP messages to detect activity completion
- The NestJS backend starts workflows via Temporal client and receives completion signals

**Retry policy**: Activities retry up to 3 times with exponential backoff for transient LLM API failures. Non-retryable errors (invalid claim, missing API keys) fail immediately.

**Supersedes**: ADR-0009 (Hub-and-Spoke MCP Topology) and ADR-0010 (Stateless Orchestrator) -- Temporal replaces both the MCP control plane and the manual state reconstruction mechanism.

### Consequences

- Good, because orchestrator recovery is automatic -- Temporal replays workflow from event history after a crash
- Good, because retry policies are declarative and configurable per activity
- Good, because parallel fan-out is native to Temporal (concurrent activity execution)
- Good, because the Temporal UI shows workflow state, activity history, and failure details
- Bad, because Temporal server is an additional infrastructure component (self-hosted or Temporal Cloud)
- Bad, because Temporal SDK concepts (workflows, activities, workers, task queues) have a learning curve
- Neutral, because the Redis Streams data plane is unchanged -- agents still publish observations to their streams

## More Information

- Supersedes [ADR-0009](0009-hub-and-spoke-mcp-topology.md) (Hub-and-Spoke MCP Topology)
- Supersedes [ADR-0010](0010-stateless-orchestrator.md) (Stateless Orchestrator)
- ADR-0012: Redis Streams Transport (data plane unchanged)
- ADR-0014: Three-Service Architecture (agent service runs Temporal workers)
