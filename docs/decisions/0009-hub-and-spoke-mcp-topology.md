---
status: "superseded by [ADR-0016](0016-temporal-agent-orchestration.md)"
date: 2026-04-08
deciders: []
---

# ADR-0009: Hub-and-Spoke MCP Topology

## Context and Problem Statement

MCP (Model Context Protocol) is used as the control plane between the orchestrator and subagents. A design choice exists between a hub-and-spoke topology (all MCP communication flows through the orchestrator) and a peer-to-peer topology (subagents communicate directly with one another via MCP).

Peer-to-peer MCP would allow subagents to request data from one another directly, potentially reducing latency and orchestrator load. However, it introduces implicit coupling: each subagent must know the capabilities, addresses, and availability of other subagents. Adding or replacing an agent requires updating all agents that communicate with it.

Hub-and-spoke keeps subagents isolated. Each subagent exposes an MCP server with its own tool surface. The orchestrator holds all MCP client connections. Subagents do not know other subagents exist.

## Decision Drivers

- Subagents must remain isolated and independently replaceable
- Adding or replacing an agent must not require updating other agents
- The orchestrator must maintain full visibility of all agent interactions
- Implicit coupling between subagents must be avoided

## Considered Options

1. **Peer-to-peer MCP** — Subagents communicate directly with one another via MCP. Reduces latency but introduces implicit coupling and requires each subagent to know the capabilities, addresses, and availability of other subagents.
2. **Hub-and-spoke MCP** — All MCP communication flows through the orchestrator. Subagents are MCP servers only; the orchestrator is the sole MCP client. No subagent-to-subagent MCP connections.

## Decision Outcome

Chosen option: "Hub-and-spoke MCP", because the orchestrator is the sole MCP client. Subagents are MCP servers only. No subagent-to-subagent MCP connections are permitted.

Two interaction patterns are supported:

**Pull pattern** — subagent tells orchestrator how to retrieve data:
```
Orchestrator → MCP → Subagent: invoke tool
Subagent → MCP → Orchestrator: "read observations from stream X"
Orchestrator reads from Redis Stream, returns data to subagent via MCP
Subagent reasons, publishes observations to its own stream
```

**Push pattern** — orchestrator tells subagent where to send output:
```
Orchestrator → MCP → Subagent: "analyze X, publish findings to your stream"
Subagent reasons, publishes observations to its Redis Stream
Orchestrator monitors stream for STOP message
```

### Consequences

- Good, because subagents are stateless with respect to other agents — an agent can be restarted, replaced, or scaled without notifying other agents
- Good, because the orchestrator maintains the DAG of agent dependencies and the mapping of which agent owns which observation codes
- Bad, because the orchestrator is the single point of failure for the MCP control plane — if the orchestrator process fails, in-flight MCP calls are lost
- Neutral, because observations already written to Redis Streams are not affected by orchestrator failure

## More Information

Superseded by [ADR-0016](0016-temporal-agent-orchestration.md). Temporal.io replaces MCP as the control plane. The orchestrator is now a Temporal workflow that dispatches agent activities. Redis Streams remains the data plane for observations.
