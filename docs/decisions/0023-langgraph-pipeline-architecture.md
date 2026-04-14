---
status: proposed
date: 2026-04-14
deciders: [mel, mayor]
---

# ADR-0023: Monolithic LangGraph Pipeline Architecture

## Context and Problem Statement

ADR-0022 identified nine simplification targets (S1-S9) in the current five-layer agent execution stack. Concurrently, emma and dave produced openspec plans for consolidating 11 agents into 5 and migrating each to LangGraph. However, both ADR-0022's "targeted simplification" and the consolidation plans preserve the same fundamental pattern: **each agent is a separate Temporal activity**, orchestrated by a Temporal workflow that manages the three-phase DAG.

This pattern has structural costs:

1. **Inter-agent data flows through Redis Streams** — Phase 2 agents read Phase 1 observations from Redis, requiring stream lifecycle management, key formatting conventions, and error handling for missing streams (the root cause of Finding S5's latent bug).
2. **Temporal workflow complexity scales with agent count** — Even after 11→5 consolidation, the workflow manages phase dispatch, parallel gather, completion tracking, and per-phase timeout configuration.
3. **Lifecycle duplication persists** — ADR-0022 S1 identifies that `run_agent_activity` and handlers both manage START/STOP/heartbeat. Even after S1 unification, each agent still needs its own activity registration, handler lookup, and stream key.
4. **Observation publishing to Redis is the SSE data plane** — This must survive any refactoring, as the frontend relies on SSE relay of progress events.

A simpler architecture is possible: **one LangGraph StateGraph** that represents the entire claim verification pipeline, running inside **one Temporal activity**. Data flows through LangGraph state instead of Redis inter-agent reads. Observations are still published to Redis for SSE progress tracking, but they flow from graph nodes, not from inter-activity stream reads.

## Decision Drivers

- Eliminate inter-agent stream coupling (the source of S5's bug and S2's conflation)
- Reduce Temporal workflow to its natural role: API orchestration (validate → execute → persist → notify)
- Preserve SSE progress tracking for the frontend (Redis observation publishing continues)
- Leverage emma's consolidation work (11→5 agents) as the node structure for the pipeline
- Preserve dave's directory consolidation (coverage 3→1 file layout)
- Enable LangGraph's native features: checkpointing, conditional edges, state-based routing
- Keep the migration incremental — the pipeline can be built node-by-node

## Current State (Post-Consolidation)

After emma's and dave's committed work, the agent landscape is:

| Phase | Agent | Pattern | Status |
|-------|-------|---------|--------|
| 1 | intake (ingestion + claim-detector + entity-extractor) | Planned consolidation | emma openspec ready |
| 2a | evidence (claimreview-matcher + domain-evidence) | Committed | 1f98a05 on crew/mel |
| 2a | coverage (coverage-left + center + right) | Planned consolidation | emma + dave openspec ready |
| 2b+3 | validation (source-validator + blindspot-detector) | Committed | 65c4226 on main |
| 4 | synthesizer | Planned LangGraph migration | emma openspec ready |

## Considered Options

### Option 1: Continue ADR-0022 Targeted Simplification

Keep each consolidated agent as a separate Temporal activity. Apply S1-S9 fixes. Workflow orchestrates 5 agents across 3 phases.

- Pro: Smallest diff from current state
- Con: Preserves inter-agent Redis coupling, lifecycle duplication, workflow complexity
- Con: S1-S9 fixes are mostly moot if we restructure anyway

### Option 2: Monolithic LangGraph Pipeline (ONE graph, ONE activity)

Build one `StateGraph` with 5 nodes (intake → evidence/coverage → validation → synthesizer). Temporal workflow reduces to: validate input → `execute_activity(run_pipeline)` → persist verdict → notify frontend.

- Pro: Eliminates all inter-agent stream coupling
- Pro: Temporal workflow becomes trivial (~30 lines)
- Pro: LangGraph state replaces Redis inter-agent reads
- Pro: LangGraph checkpointing provides mid-pipeline durability
- Pro: Conditional edges enable dynamic routing (skip coverage if no NewsAPI key, etc.)
- Con: Single activity timeout must cover entire pipeline (~120s)
- Con: Loss of per-agent Temporal retry (compensated by LangGraph-level retry)
- Con: Larger blast radius per activity failure

### Option 3: Subgraph Composition (middle ground)

Each consolidated agent is a LangGraph subgraph. A parent graph composes them. Each subgraph can run as a separate Temporal activity OR as a node in the parent graph.

- Pro: Migration flexibility — can start with separate activities and merge later
- Pro: Preserves per-subgraph retry semantics
- Con: Adds subgraph composition complexity
- Con: Still needs inter-subgraph data passing (state or streams)

## Decision Outcome

Chosen option: **Option 2 — Monolithic LangGraph Pipeline**, because it produces the simplest final architecture and the consolidated agents (emma's work) map directly to graph nodes. The inter-agent Redis coupling is the root cause of multiple ADR-0022 findings, and eliminating it solves them structurally rather than patching around them.

Option 3 is the migration path: build each agent as a self-contained subgraph first (reusing emma's openspec designs), then compose them into the monolithic pipeline.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Temporal Workflow (ClaimVerificationWorkflow)                    │
│                                                                 │
│  1. validate_input(claim_text) → ClaimInput                     │
│  2. result = execute_activity(run_pipeline, ClaimInput)          │
│  3. persist_verdict(result)                                     │
│  4. notify_frontend(result.session_id)                          │
│                                                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │ ONE activity
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ LangGraph StateGraph: ClaimVerificationPipeline                 │
│                                                                 │
│  ┌──────────┐    ┌──────────────────────┐    ┌──────────────┐   │
│  │  intake   │───▶│  fan_out (parallel)  │───▶│  validation  │   │
│  │  (5 tools)│    │                      │    │  (5 tools)   │   │
│  └──────────┘    │  ┌────────────────┐  │    └──────┬───────┘   │
│                  │  │   evidence     │  │           │           │
│                  │  │   (4 tools)    │  │           ▼           │
│                  │  └────────────────┘  │    ┌──────────────┐   │
│                  │  ┌────────────────┐  │    │ synthesizer  │   │
│                  │  │   coverage     │  │    │ (4 tools)    │   │
│                  │  │   (3 tools)    │  │    └──────────────┘   │
│                  │  └────────────────┘  │                       │
│                  └──────────────────────┘                       │
│                                                                 │
│  State: PipelineState (TypedDict)                               │
│  Observations: Published to Redis for SSE (side-effect, not     │
│                inter-node communication)                        │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline State

```python
class PipelineState(TypedDict):
    # Input
    claim_text: str
    claim_url: str | None
    submission_date: str
    run_id: str
    session_id: str

    # Phase 1: Intake output
    normalized_claim: str
    claim_domain: str
    check_worthy_score: float
    entities: dict[str, list[str]]  # {persons: [...], orgs: [...], ...}
    is_check_worthy: bool

    # Phase 2a: Evidence output
    claimreview_matches: list[dict]
    domain_sources: list[dict]
    evidence_confidence: float | None

    # Phase 2a: Coverage output
    coverage_left: list[dict]
    coverage_center: list[dict]
    coverage_right: list[dict]
    framing_analysis: dict

    # Phase 2b+3: Validation output
    validated_urls: list[dict]
    convergence_score: float
    citations: list[dict]
    blindspot_score: float
    blindspot_direction: str

    # Phase 4: Synthesizer output
    verdict: str
    confidence: float
    narrative: str
    verdict_observations: list[dict]

    # Metadata
    observations: list[dict]  # Running log, published to Redis as side-effect
    errors: list[str]         # Non-fatal errors from partial failures
```

### Node Design

Each node follows a consistent pattern:

```python
async def intake_node(state: PipelineState, config: RunnableConfig) -> dict:
    """Phase 1: Claim intake, normalization, entity extraction."""
    ctx = _get_pipeline_context(config)  # Redis client, run_id, etc.

    # Run the intake subgraph (or tool-calling agent)
    result = await intake_agent.ainvoke(state, config)

    # Publish observations to Redis (side-effect for SSE)
    await ctx.publish_observations("intake", result["observations"])

    # Return state updates (LangGraph merges these into PipelineState)
    return {
        "normalized_claim": result["normalized_claim"],
        "claim_domain": result["claim_domain"],
        "check_worthy_score": result["check_worthy_score"],
        "entities": result["entities"],
        "is_check_worthy": result["is_check_worthy"],
    }
```

### Fan-Out / Fan-In

LangGraph's `Send` API enables parallel execution of evidence and coverage nodes:

```python
def fan_out_router(state: PipelineState) -> list[Send]:
    """Route to parallel Phase 2a nodes."""
    if not state["is_check_worthy"]:
        return [Send("synthesizer", state)]  # Skip to verdict: NOT_CHECK_WORTHY

    sends = [Send("evidence", state)]
    if has_newsapi_key():
        sends.append(Send("coverage", state))
    return sends
```

### Temporal Workflow (Simplified)

```python
@workflow.defn
class ClaimVerificationWorkflow:
    @workflow.run
    async def run(self, input: ClaimInput) -> ClaimResult:
        # 1. Validate
        validated = await workflow.execute_activity(
            validate_claim_input, input,
            start_to_close_timeout=timedelta(seconds=5),
        )

        # 2. Run pipeline (ONE activity, ONE graph)
        result = await workflow.execute_activity(
            run_langgraph_pipeline, validated,
            start_to_close_timeout=timedelta(seconds=180),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                maximum_attempts=2,
                non_retryable_error_types=["InvalidClaimError", "NotCheckWorthyError"],
            ),
        )

        # 3. Persist
        await workflow.execute_activity(
            persist_verdict, result,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # 4. Notify
        await workflow.execute_activity(
            notify_frontend, PersistResult(session_id=input.session_id),
            start_to_close_timeout=timedelta(seconds=5),
        )

        return result
```

### Observation Publishing (SSE Continuity)

Observations continue to be published to Redis Streams for SSE relay. The key difference: observations are a **side-effect** of graph nodes, not the inter-node communication mechanism.

```python
# Each node publishes observations to Redis for frontend progress tracking
# Stream key format unchanged: reasoning:{runId}:{agent_name}
# Progress stream unchanged: progress:{runId}

async def _publish_node_observations(ctx: PipelineContext, agent_name: str, obs: list[dict]):
    """Publish observations to Redis as side-effect. Does NOT affect graph state."""
    stream_key = f"reasoning:{ctx.run_id}:{agent_name}"
    await ctx.stream.publish_start(stream_key, agent_name)
    for ob in obs:
        await ctx.stream.publish(stream_key, ob)
    await ctx.stream.publish_stop(stream_key, agent_name)
```

### Heartbeat Strategy

The single activity heartbeats via Temporal's activity heartbeat mechanism. Each node updates the heartbeat detail with its current phase:

```python
@activity.defn
async def run_langgraph_pipeline(input: ValidatedClaim) -> PipelineResult:
    # LangGraph graph with heartbeat callback
    async def heartbeat_callback(node_name: str):
        activity.heartbeat(f"executing:{node_name}")

    config = {"configurable": {"heartbeat_fn": heartbeat_callback, ...}}
    result = await pipeline_graph.ainvoke(initial_state, config)
    return PipelineResult.from_state(result)
```

### Error Handling

| Error Type | Handling |
|-----------|----------|
| Invalid claim input | `validate_claim_input` raises `InvalidClaimError` (non-retryable) |
| Not check-worthy | `intake_node` sets `is_check_worthy=False`, fan-out routes to synthesizer directly |
| Single node failure (e.g., evidence API down) | Node catches, records partial error in state, pipeline continues with degraded data |
| Full pipeline failure | Temporal retries the activity (max 2 attempts) |
| Pipeline timeout (>180s) | Temporal cancels the activity; LangGraph checkpoint preserves partial state |

### Migration Order

Build the pipeline incrementally, one node at a time, validating each before adding the next:

| Step | What | Depends On | Source |
|------|------|-----------|--------|
| M0 | Pipeline infrastructure: `PipelineState`, `PipelineContext`, graph skeleton, heartbeat | Nothing | New |
| M1 | `intake_node` — consolidate ingestion + claim-detector + entity-extractor | M0 | emma: intake-consolidation |
| M2 | `evidence_node` — already consolidated (claimreview + domain-evidence) | M0 | emma: evidence-consolidation (committed) |
| M3 | `coverage_node` — consolidate coverage-left/center/right | M0 | emma: coverage-consolidation, dave: consolidate-coverage-directory |
| M4 | `validation_node` — already consolidated (source-validator + blindspot) | M0 | emma: validation-consolidation (committed) |
| M5 | `synthesizer_node` — LangGraph migration for verdict synthesis | M0 | emma: synthesizer-langgraph |
| M6 | Graph composition — connect nodes with fan-out/fan-in edges | M1-M5 | New |
| M7 | Temporal workflow simplification — replace DAG-driven multi-activity workflow | M6 | New (supersedes dave: idiomatic-temporal-workflow) |
| M8 | Cleanup — delete old handler directories, FanoutBase, LangGraphBase, DAG, dead code | M7 | ADR-0022 S5, S9 |

M1-M5 can proceed in parallel (each node is independently buildable and testable).

## Impact on ADR-0022 Findings

| Finding | Status Under New Architecture |
|---------|-------------------------------|
| S1: Duplicate stream lifecycle | **Eliminated** — No handler-level lifecycle. Pipeline graph has no START/STOP per node; the single activity manages lifecycle. |
| S2: FanoutBase conflates context + lifecycle | **Eliminated** — FanoutBase deleted. Context flows through `PipelineState`. |
| S3: _execute() duplication | **Eliminated** — No per-agent `_execute()`. Each node is a plain async function. |
| S4: Programmatic .ainvoke() on @tool | **Eliminated** — Tools are called as plain functions within nodes, or as LangGraph tools within subgraph agents. |
| S5: StreamNotFoundError duplication | **Eliminated** — No inter-agent stream reads. Data flows through state. (Fix the bug first as P0 since it affects current production.) |
| S6: Broader _execute() duplication | **Eliminated** — Same as S3. |
| S7: _heartbeat_loop duplication | **Eliminated** — Single heartbeat in the activity wrapper. |
| S8: _publish_progress abstraction leak | **Resolved** — Progress publishing moves to `PipelineContext.publish_observations()`. |
| S9: Orphaned handler registrations | **Resolved in M8** — All old handler directories deleted. |
| S10: ToolRuntime dead code | **Resolved in M8** — Deleted with old infrastructure. |
| S11: DAG is clean (KEEP) | **Superseded** — DAG replaced by LangGraph graph edges. |
| S12: No duplicate workflow (NON-ISSUE) | **Still non-issue** — Single workflow file, further simplified. |

## Impact on Existing Work

### Committed Work (KEEP)

| Commit | What | Status |
|--------|------|--------|
| 65c4226 | validation consolidation (source-validator + blindspot → validation) | KEEP — validation logic becomes M4 node |
| 1f98a05 | evidence consolidation (claimreview + domain-evidence → evidence) | KEEP — evidence logic becomes M2 node |

### Dave's OpenSpec Changes

| Change | Classification | Rationale |
|--------|---------------|-----------|
| consolidate-coverage-directory | **KEEP** | File layout cleanup (3 dirs → 1) is valid regardless of architecture. Feeds into M3. |
| consolidate-agent-infrastructure | **DISCARD** | Generalizing FanoutBase→AgentBase is moot when FanoutBase is deleted in M8. |
| idiomatic-temporal-workflow | **DISCARD** | Temporal workflow is radically simplified in M7, not iteratively improved. |
| refactor-claim-detector | **DISCARD** | Claim-detector handler is absorbed into intake_node (M1). Internal cleanup of a handler that won't exist. |
| workflow-resilience | **MODIFY→M6/M7** | Cancellation signal and partial-failure concepts apply but implementation differs. Cancellation: Temporal signal triggers `graph.acancel()`. Partial failure: node-level error handling in PipelineState. ApplicationError self-declaration: still valid for the 4 Temporal activities. |
| deduplicate-nfr-scenarios | **KEEP** | Documentation cleanup, architecture-independent. |
| extract-feature-requirements | **KEEP** | Documentation cleanup, architecture-independent. |
| user-journey-features | **KEEP** | Documentation cleanup, architecture-independent. |

### Emma's OpenSpec Changes

| Change | Classification | Rationale |
|--------|---------------|-----------|
| langgraph-infrastructure | **MODIFY** | AgentContext/observation-publishing concepts survive but as PipelineContext. Per-agent LangGraphBase is replaced by pipeline graph. |
| intake-consolidation | **KEEP→M1** | 3 agents → 1 with 5 tools. Becomes intake_node. Tool designs are directly reusable. |
| evidence-consolidation | **KEEP→M2** | Already committed. Logic becomes evidence_node. |
| coverage-consolidation | **KEEP→M3** | 3 → 1 with parameterized tools. Becomes coverage_node. |
| validation-consolidation | **KEEP→M4** | Already committed. Logic becomes validation_node. |
| synthesizer-langgraph | **KEEP→M5** | LangGraph migration with 4 tools. Becomes synthesizer_node. |
| refactor-entity-extractor-langgraph | **DISCARD** | Entity extractor absorbed into intake (M1). |
| blindspot-detector-comprehensibility | **DISCARD** | Blindspot absorbed into validation (M4). |
| claimreview-matcher-comprehensibility | **DISCARD** | Claimreview absorbed into evidence (M2). |

### Open Beads (52 total from ADR-0022 S1-S9)

| Epic | Section | Classification | Rationale |
|------|---------|---------------|-----------|
| sr-ubh | S6: StreamNotFoundError bug | **KEEP (P0)** | Fix the bug in current production code before migration. |
| sr-bb9 | S5/S9: Dead code removal | **MODIFY** | Orphaned directories (bb9.4-6) are immediate cleanup. ToolRuntime (bb9.1-3) is immediate cleanup. Other items (bb9.7) superseded by M8. |
| sr-0hq | S1: Unify lifecycle | **DISCARD** | Lifecycle unification is moot when the entire handler layer is replaced. |
| sr-9ss | S3: Template method hook | **DISCARD** | LangGraphBase template methods are moot when LangGraphBase is replaced. |
| sr-pkh | S4: Core function extraction | **MODIFY** | Core function extraction concept valid — tools need clean function signatures for graph nodes. But scope and location change. |
| sr-zx8 | S9: Verification | **DISCARD** | Verification criteria are architecture-specific. New pipeline needs its own verification checklist. |
| sr-2p7.* | S2: Context loading extraction | **DISCARD** | Context loading through Redis streams is replaced by PipelineState. |
| sr-wisp-* | openspec-to-beads | **MODIFY** | Still needed but for the new plan's migration steps. |

## Consequences

- Good, because inter-agent stream coupling (root cause of S5 bug, S1/S2 complexity) is eliminated structurally
- Good, because Temporal workflow reduces from ~200 lines of DAG orchestration to ~30 lines of API orchestration
- Good, because emma's consolidation designs (5 agents with well-defined tools) map directly to pipeline nodes
- Good, because dave's coverage directory consolidation is preserved and accelerated
- Good, because LangGraph checkpointing provides mid-pipeline durability without Temporal per-agent activities
- Good, because 7 of 9 ADR-0022 findings are eliminated by the architecture change rather than patched
- Bad, because single activity timeout (180s) must cover entire pipeline; no per-phase Temporal retry
- Bad, because migration touches every agent file (compensated by incremental M0-M8 approach)
- Bad, because LangGraph parallel execution (Send API) is less battle-tested than Temporal's gather pattern
- Neutral, because Redis observation publishing is preserved (SSE compatibility), but stream reads between agents are eliminated

## More Information

- ADR-0022: Simplify LangGraph + Temporal Layering (findings this builds on)
- ADR-0016: Temporal.io for Agent Orchestration (superseded for agent orchestration; Temporal retains API workflow role)
- ADR-0012: Redis Streams Transport (unchanged for observation publishing/SSE; eliminated for inter-agent reads)
- Reference pattern: `services/agent-service/docs/reference-langgraph-temporal-pattern.py`
- Emma's consolidation openspec: `crew/emma/openspec/changes/` (intake, evidence, coverage, validation, synthesizer)
- Dave's coverage cleanup openspec: `crew/dave/openspec/changes/consolidate-coverage-directory`
