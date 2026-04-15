## Context

The agent-service runs 11 agents as separate Temporal activities, orchestrated by a DAG-driven workflow. Inter-agent data flows through Redis Streams, requiring each agent to manage stream lifecycle (START/STOP, heartbeat, progress). A five-layer execution stack (run_agent_activity -> FanoutBase -> LangGraphBase -> handler -> tools) has accumulated duplicate lifecycle management, a latent StreamNotFoundError retry bug, and dead code.

Emma consolidated 11 agents to 5 (intake, evidence, coverage, validation, synthesizer). Dave consolidated coverage directories. ADR-0022 identified 12 findings; ADR-0023 determined that a monolithic LangGraph pipeline eliminates 10 of them structurally.

The reference pattern (`services/agent-service/docs/reference-langgraph-temporal-pattern.py`) demonstrates the target: LangGraph owns reasoning, Temporal owns durability, no extra layers between them.

## Goals / Non-Goals

**Goals:**
- Replace the multi-activity DAG-driven Temporal workflow with a single LangGraph StateGraph running inside one Temporal activity
- Eliminate inter-agent Redis Stream coupling by flowing data through PipelineState
- Preserve SSE progress tracking by continuing to publish observations to Redis as side-effects
- Map emma's 5 consolidated agents directly to pipeline graph nodes
- Enable LangGraph features: conditional edges, parallel Send API, state-based routing
- Incremental migration: build and test each node independently before composing

**Non-Goals:**
- Changing the observation schema or OBX code registry
- Modifying the NestJS backend architecture or frontend
- Adding new agents or changing agent reasoning capabilities
- Migrating away from Redis for SSE observation publishing
- Changing the Temporal SDK version or cluster configuration

## Decisions

### D1. One StateGraph, one Temporal activity

**Choice**: Build one `ClaimVerificationPipeline` StateGraph with 5 nodes. Wrap it in a single `run_langgraph_pipeline` Temporal activity with 180s timeout and 30s heartbeat.

**Alternative considered**: Each consolidated agent as a separate LangGraph subgraph in its own Temporal activity. Rejected because it preserves inter-agent Redis coupling and lifecycle duplication — the root cause of most ADR-0022 findings.

### D2. PipelineState as the inter-node data plane

**Choice**: A TypedDict (`PipelineState`) carries all data between nodes. Each node reads from state and returns a dict of state updates that LangGraph merges. No node reads from Redis Streams.

**Alternative considered**: Keep Redis Streams as inter-node transport with LangGraph state as metadata only. Rejected because it defeats the purpose of the migration.

### D3. Observations as side-effects, not data plane

**Choice**: Each node publishes observations to Redis for SSE relay, but observations are a side-effect — they do not flow between nodes. Stream key format (`reasoning:{runId}:{agent}`) and progress stream (`progress:{runId}`) are unchanged.

**Alternative considered**: Stop publishing observations and use a different SSE mechanism. Rejected because it would require frontend changes and breaks the existing contract.

### D4. Fan-out via LangGraph Send API

**Choice**: After intake, a router function returns `[Send("evidence", state), Send("coverage", state)]` for parallel execution. If claim is not check-worthy, route directly to synthesizer. If no NewsAPI key, skip coverage.

**Alternative considered**: Sequential execution of evidence then coverage. Rejected because parallel execution is a key performance characteristic of the current system.

### D5. Nodes as plain async functions, not class hierarchies

**Choice**: Each node is an `async def node_name(state: PipelineState, config: RunnableConfig) -> dict` function. No FanoutBase, no LangGraphBase. Tools are either LangGraph tools (for ReAct nodes) or plain async functions (for procedural nodes).

**Alternative considered**: Keep base classes but simplify them. Rejected because the reference pattern demonstrates that plain functions are sufficient and clearer.

### D6. Incremental build order M0-M8

**Choice**: Build the pipeline infrastructure first (M0), then nodes independently (M1-M5 in parallel), then compose (M6), simplify Temporal (M7), clean up old code (M8). Each step is independently testable.

**Alternative considered**: Big-bang rewrite replacing everything at once. Rejected because it's higher risk and harder to debug.

### D7. Heartbeat via configurable callback

**Choice**: The `run_langgraph_pipeline` activity passes a heartbeat callback through LangGraph's `RunnableConfig`. Each node calls it with the current phase name. This replaces the 4 duplicated `_heartbeat_loop` implementations.

**Alternative considered**: Background heartbeat thread in the activity wrapper. Rejected because node-level heartbeat detail (e.g., "executing:evidence") provides better observability.

## Risks / Trade-offs

- **[Single activity timeout]** The entire pipeline must complete within 180s. No per-phase Temporal retry. -> Mitigation: LangGraph checkpointing for mid-pipeline durability. Node-level error handling records partial failures in state; pipeline continues with degraded data.
- **[Fan-out maturity]** LangGraph's Send API for parallel execution is less battle-tested than Temporal's gather pattern. -> Mitigation: Integration test validates parallel evidence + coverage execution. Fallback: sequential execution is a simple conditional edge change.
- **[Migration breadth]** All agent handler files are touched. -> Mitigation: Incremental M0-M8 approach. Each node is independently buildable and testable. Old handlers coexist until M8 cleanup.
- **[LangGraph version coupling]** Pipeline depends on LangGraph StateGraph, Send, and RunnableConfig APIs. -> Mitigation: Pin LangGraph version. These are stable, documented APIs.
- **[Observation publishing latency]** Publishing observations as side-effects adds I/O to each node. -> Mitigation: Async publishing. Observation publishing is already in the critical path today; no regression expected.
