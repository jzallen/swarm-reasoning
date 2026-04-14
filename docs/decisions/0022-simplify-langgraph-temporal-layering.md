---
status: accepted
date: 2026-04-14
deciders: [mel]
---

# ADR-0022: Simplify LangGraph + Temporal Layering

## Context and Problem Statement

ADR-0016 established Temporal for durable orchestration and LangGraph for agent reasoning. The implementation has grown additional abstraction layers that may add cognitive burden without proportional value. A reference pattern (`docs/reference-langgraph-temporal-pattern.py`) demonstrates the target: LangGraph owns reasoning (the entire agent graph runs inside ONE Temporal activity), Temporal owns durability (retry, persist, signal, distribute), and no extra abstraction layers sit between them.

This ADR reviews the current layering against that reference and identifies concrete simplifications.

## Current Architecture

The agent execution stack has five layers:

```
run_agent_activity          ← Temporal activity wrapper (START/STOP, heartbeat, progress)
  └─ FanoutBase.run()       ← Stream lifecycle (START/STOP, heartbeat, progress, upstream context, timeout)
       └─ LangGraphBase     ← create_react_agent factory (model, tools, prompt, context injection)
            └─ CoverageHandler / etc.  ← Domain-specific subclass
                 └─ @tool functions    ← Observation publishing via AgentContext + InjectedToolArg
```

Ten agents use three different patterns:

| Pattern | Agents | Base class |
|---------|--------|------------|
| Standalone (manual lifecycle) | ingestion-agent, claim-detector, entity-extractor | None |
| FanoutBase (manual tool calls) | source-validator, validation, domain-evidence | FanoutBase |
| LangGraphBase (LLM-driven ReAct) | coverage-left/center/right, claimreview-matcher, blindspot-detector, synthesizer | LangGraphBase(FanoutBase) |

## Findings

### Finding 1: Duplicate stream lifecycle between run_agent_activity and handlers (HIGH)

`run_agent_activity` (`activities/run_agent.py:101-168`) publishes START/STOP messages, runs a heartbeat loop, and publishes progress events. FanoutBase (`agents/fanout_base.py:71-162`) does **the same thing** — START/STOP, heartbeat loop, progress events. Standalone handlers (ClaimDetectorHandler, etc.) also manage their own START/STOP and heartbeat.

This means for FanoutBase-derived agents, the lifecycle is managed in two places. Either `_stream_client` is always `None` for these handlers (making run_agent_activity's lifecycle code dead), or we publish duplicate messages.

**Impact**: Confusing ownership. A reader cannot tell which layer is responsible for stream lifecycle without tracing the `_stream_client` initialization.

### Finding 2: FanoutBase conflates upstream context loading with stream lifecycle (MEDIUM)

FanoutBase provides two unrelated capabilities:
1. **Stream lifecycle**: START/STOP, heartbeat, timeout, progress — duplicates run_agent_activity
2. **Upstream context loading**: `_load_upstream_context()` reads Phase 1 streams to build `ClaimContext`

The context loading (lines 187-234) is genuinely useful — it reads from claim-detector, ingestion-agent, and entity-extractor streams to assemble normalized claim, domain, entities. But bundling it with lifecycle management forces agents to inherit the full FanoutBase stack even if they only need the context.

**Impact**: Agents that don't need FanoutBase's lifecycle (because run_agent_activity handles it) still inherit it for context loading.

### Finding 3: CoverageHandler._execute() duplicates LangGraphBase._execute() (HIGH)

`coverage_core.py:367-424` is a near-copy of `langgraph_base.py:54-98`. The only difference: CoverageHandler injects source IDs and source JSON into the human message. This is a textbook case for a template method or hook.

Both methods:
1. Create AgentContext
2. Create ChatAnthropic model
3. Get tools and prompt
4. Suppress deprecation warnings
5. Call create_react_agent
6. Build input message
7. Call graph.ainvoke()
8. Sync seq_counter

**Impact**: Every change to graph construction must be made in two places. As more agent types override `_execute()` for input enrichment, this compounds.

### Finding 4: Programmatic .ainvoke() on @tool functions (MEDIUM)

Three handlers call `@tool`-decorated functions via `.ainvoke()` with JSON-serialized arguments:

- **claim-detector** (`handler.py:129-141`): `normalize_claim.ainvoke({"claim_text": ..., "context": agent_ctx})`
- **source-validator** (`handler.py:90-139`): `extract_urls.ainvoke(...)`, `validate_urls.ainvoke(...)`, etc.
- **validation** (`handler.py:89-111`): `compute_convergence_score.ainvoke(...)`, `analyze_blindspots.ainvoke(...)`

These tools were designed for LLM tool-calling (they have docstrings, JSON schemas, `InjectedToolArg` annotations). Using them programmatically means:
- JSON serialization/deserialization overhead on every call
- The `@tool` decorator's input validation and schema generation serve no purpose
- Tool docstrings (written for LLM consumption) are noise for programmatic callers

**Impact**: Cognitive overhead. A reader must understand that `.ainvoke()` on a `@tool` is functionally equivalent to calling the underlying function, just with LangChain plumbing in the way.

### Finding 5: StreamNotFoundError class duplication (HIGH — latent bug)

`fanout_base.py:51` defines its own `StreamNotFoundError`. `_utils.py:34` defines a separate `StreamNotFoundError`. `run_agent_activity` imports from `_utils` and lists it in `NON_RETRYABLE_ERRORS` (line 98). But FanoutBase raises its **local** class (line 202), which is a different Python type. Temporal's retry logic catches `NON_RETRYABLE_ERRORS` at line 193 — FanoutBase's `StreamNotFoundError` won't match, so Temporal will retry the activity indefinitely on a missing stream instead of failing fast.

**Impact**: Agents that can't find upstream data (e.g., claim-detector stream missing) will retry until the activity timeout instead of failing immediately with a non-retryable error.

### Finding 6: _execute() duplication is broader than CoverageHandler (HIGH)

The `create_react_agent` construction block is duplicated in **four** places, not just `CoverageHandler`:
- `langgraph_base.py:54-98` (canonical)
- `coverage_core.py:367-424` (adds source IDs to message)
- `synthesizer/handler.py:103-150` (adds synthesis-specific message)
- `blindspot_detector/handler.py:88-135` (adds blindspot-specific message)

All four duplicate: lazy import, `AgentContext` construction, `ChatAnthropic` instantiation, `warnings.catch_warnings()` suppression, `create_react_agent()` call, `graph.ainvoke()`, and `seq_counter` sync. The only variation is the human message content.

### Finding 7: _heartbeat_loop duplicated across 4 files (LOW)

Identical `_heartbeat_loop` static methods exist in `FanoutBase`, `IngestionAgentHandler`, `ClaimDetectorHandler`, and `EntityExtractorHandler`. Should be a shared utility in `_utils.py`.

### Finding 8: _publish_progress leaks ReasoningStream abstraction (MEDIUM)

`run_agent.py:213` accesses `_stream_client._redis` directly for progress events, bypassing the `ReasoningStream` interface. This ties the activity to the `RedisReasoningStream` implementation and would break if the transport abstraction (ADR-012) is swapped.

### Finding 9: Orphaned handler registrations after agent consolidation (MEDIUM)

After consolidation (commit 65c4226), three handler directories remain registered but are unreachable via the DAG:
- `claimreview-matcher` (consolidated into `evidence`)
- `domain-evidence` (consolidated into `evidence`)
- `blindspot-detector` (consolidated into `validation`)

These handlers import and register via `@register_handler` but are never dispatched by the workflow. If dispatched by name, `_resolve_phase` falls back to `INGESTION` phase, producing incorrect stream metadata.

### Finding 10: ToolRuntime is unused dead code (LOW)

`ToolRuntime` (`tool_runtime.py:90-105`) is a one-property wrapper around `AgentContext`. No production code uses it — agents create `AgentContext` directly and pass it through LangGraph's `context_schema`. The class exists only in test files.

**Impact**: Minimal, but adds confusion about the "right" way to inject context.

### Finding 11: DAG definition is clean and justified (KEEP)

`dag.py` (52 lines) is a clean declarative definition. The workflow indexes into it for phase-specific dispatch. It serves as a single source of truth for agent membership and execution order. Unlike the reference pattern (single workflow, single agent), this system orchestrates 10 agents across three phases — a static DAG is appropriate.

### Finding 12: No duplicate workflow file (NON-ISSUE)

The concern about `temporal/workflow.py` vs `workflows/claim_verification.py` is moot — only the latter exists. `src/swarm_reasoning/temporal/` contains only `__init__.py` and `errors.py`.

## Decision Drivers

- Reduce cognitive burden for developers understanding the agent execution path
- Match the reference pattern's clarity: LangGraph for reasoning, Temporal for durability
- Eliminate duplicate lifecycle management
- Preserve the capabilities that genuinely pull weight (upstream context loading, LangGraph agent factory, DAG-driven dispatch)

## Considered Options

1. **Full flatten** — Remove FanoutBase and LangGraphBase entirely. Each agent is a plain function (like the reference pattern) called as a single Temporal activity. Context loading and graph construction are helper functions, not base classes.
2. **Targeted simplification** — Keep the base class hierarchy but fix the specific issues: deduplicate lifecycle, extract context loading, add template method hooks, remove dead code.
3. **Status quo** — Leave the architecture as-is.

## Decision Outcome

Chosen option: **"Targeted simplification"**, because the base classes provide real value for 7 of 10 agents (code reuse across coverage-*, validation, domain-evidence, synthesizer, etc.), but the specific duplication and dead code issues should be addressed. A full flatten would trade class hierarchy complexity for function sprawl across 10 agent files.

### Concrete Changes

#### S1. Unify stream lifecycle ownership

Decide whether `run_agent_activity` or the handler owns START/STOP, heartbeat, and progress. Recommendation: **run_agent_activity owns lifecycle**, handlers own reasoning.

- Remove START/STOP publishing from FanoutBase and standalone handlers
- Remove heartbeat loops from FanoutBase and standalone handlers (run_agent_activity already heartbeats)
- Remove progress publishing from FanoutBase (run_agent_activity already does this)
- FanoutBase.run() becomes `execute()` — just upstream context loading + timeout + delegate to `_execute()`

This aligns with the reference pattern: the Temporal activity wraps the agent, not the other way around.

**Files to modify**: `fanout_base.py`, `claim_detector/handler.py`, `entity_extractor/handler.py`, `ingestion_agent/handler.py`

#### S2. Extract upstream context loading into a standalone function

Move `_load_upstream_context()` out of FanoutBase into a standalone `async def load_claim_context(stream, run_id) -> ClaimContext` function. Agents that need context call it directly. Agents that don't (Phase 1) skip it.

**Files to modify**: `fanout_base.py` → new `context.py`; update imports in all FanoutBase subclasses

#### S3. Add _build_input_message() hook to LangGraphBase

Replace CoverageHandler._execute() duplication with a hook:

```python
# In LangGraphBase:
def _build_input_message(self, context: ClaimContext) -> str:
    """Build the input message. Override to enrich with agent-specific data."""
    return _format_claim_input(context)

# In CoverageHandler:
def _build_input_message(self, context: ClaimContext) -> str:
    base = super()._build_input_message(context)
    sources = self._get_sources()
    source_ids = ",".join(s["id"] for s in sources[:20])
    return f"{base}\n\nSource IDs: {source_ids}\nSources data: {json.dumps(sources)}"
```

**Files to modify**: `langgraph_base.py`, `coverage_core.py`, `synthesizer/handler.py`, `blindspot_detector/handler.py`

#### S4. Extract core logic from @tool wrappers for programmatic callers

For tools called programmatically, extract the business logic into plain async functions. Keep the @tool wrappers as thin facades for LLM consumption:

```python
# Core function (programmatic callers use this):
async def normalize_claim_text(claim_text: str, ctx: AgentContext) -> str:
    ...

# LLM tool wrapper (LangGraph agents use this):
@tool
async def normalize_claim(claim_text: str, context: Annotated[AgentContext, InjectedToolArg]) -> str:
    """Normalize a claim..."""  # docstring for LLM
    return await normalize_claim_text(claim_text, context)
```

**Files to modify**: `claim_detector/tools/normalize.py`, `claim_detector/tools/score.py`, `source_validator/tools/*.py`, `validation/tools/*.py`

#### S5. Delete ToolRuntime

Remove the `ToolRuntime` class. Update test files that reference it.

**Files to modify**: `tool_runtime.py`, `tests/unit/agents/test_tool_runtime.py`, `tests/unit/agents/test_observation_tools.py`

#### S6. Fix StreamNotFoundError class duplication (BUG FIX)

Delete the local `StreamNotFoundError` in `fanout_base.py:51` and import from `_utils` instead. This is a latent bug — FanoutBase's local class is not caught by the activity's `NON_RETRYABLE_ERRORS` tuple, causing Temporal to retry stream-not-found errors indefinitely.

**Files to modify**: `fanout_base.py`

#### S7. Extract _heartbeat_loop into shared utility

Move the duplicated `_heartbeat_loop` static method into `_utils.py`. Remove identical copies from `FanoutBase`, `IngestionAgentHandler`, `ClaimDetectorHandler`, and `EntityExtractorHandler`.

**Files to modify**: `_utils.py`, `fanout_base.py`, `ingestion_agent/handler.py`, `claim_detector/handler.py`, `entity_extractor/handler.py`

#### S8. Fix _publish_progress abstraction leak

Add a `publish_progress(key, data)` method to the `ReasoningStream` interface (or use a raw Redis reference exposed properly) instead of accessing `_stream_client._redis` directly. This preserves the transport abstraction (ADR-012).

**Files to modify**: `activities/run_agent.py`, `streams/reasoning_stream.py` (or equivalent interface)

#### S9. Remove orphaned handler directories

Delete or archive `claimreview_matcher/`, `domain_evidence/`, and `blindspot_detector/` handler directories and their `@register_handler` decorators. These are unreachable via the DAG after the consolidation in commit 65c4226.

**Files to delete**: `agents/claimreview_matcher/`, `agents/domain_evidence/`, `agents/blindspot_detector/`

### Consequences

- Good, because the execution path from Temporal activity → agent reasoning is clear and linear
- Good, because lifecycle ownership is unambiguous (run_agent_activity owns it)
- Good, because CoverageHandler, SynthesizerHandler, and future agent types can customize input without copy-pasting _execute()
- Good, because programmatic tool callers skip LangChain's invoke machinery
- Good, because S6 fixes a latent bug where stream-not-found errors retry indefinitely
- Good, because S9 removes dead code paths that could produce incorrect stream metadata if accidentally dispatched
- Bad, because S1 and S2 touch every agent handler (migration risk)
- Bad, because S4 doubles the function count for affected tools (core + wrapper)

### Priority

| Change | Impact | Effort | Priority |
|--------|--------|--------|----------|
| S6. Fix StreamNotFoundError duplication | High (bug fix) | Low | P0 |
| S1. Unify lifecycle | High | Medium | P1 |
| S3. Template method hook | High | Low | P1 |
| S5. Delete ToolRuntime | Low | Low | P1 |
| S9. Remove orphaned handlers | Medium | Low | P1 |
| S2. Extract context loading | Medium | Medium | P2 |
| S4. Core + wrapper split | Medium | Medium | P2 |
| S7. Shared _heartbeat_loop | Low | Low | P2 |
| S8. Fix _publish_progress leak | Medium | Low | P2 |

## More Information

- Reference pattern: `services/agent-service/docs/reference-langgraph-temporal-pattern.py`
- ADR-0016: Temporal.io for Agent Orchestration (the foundation this builds on)
- ADR-0012: Redis Streams Transport (data plane, unchanged by this proposal)
