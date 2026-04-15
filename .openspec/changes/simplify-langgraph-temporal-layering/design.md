## Context

The agent-service executes 10 agents across a three-phase DAG (sequential ingestion, parallel fanout, sequential synthesis). Each agent runs as a Temporal activity. The current implementation has a five-layer execution stack: `run_agent_activity` → `FanoutBase.run()` → `LangGraphBase` → domain handler → `@tool` functions.

ADR-0022 identified that stream lifecycle management (START/STOP, heartbeat, progress) is duplicated between `run_agent_activity` and `FanoutBase`, that the `create_react_agent` construction block is copy-pasted across 4 handler files, and that a `StreamNotFoundError` class duplication creates a latent retry bug.

The reference pattern (`services/agent-service/docs/reference-langgraph-temporal-pattern.py`) demonstrates the target: one Temporal activity wraps the entire LangGraph agent. Temporal owns durability; LangGraph owns reasoning. No extra layers.

## Goals / Non-Goals

**Goals:**
- Single owner for stream lifecycle (START/STOP, heartbeat, progress): `run_agent_activity`
- Handlers responsible only for reasoning — no lifecycle management code
- Upstream context loading available as a standalone function, not bundled with lifecycle
- LangGraph agents customize input messages via a hook, not by copy-pasting `_execute()`
- Programmatic tool callers bypass LangChain's `@tool` invoke machinery
- Fix the `StreamNotFoundError` class duplication bug (P0)
- Remove orphaned handler directories and dead code

**Non-Goals:**
- Full flatten to remove base classes entirely (ADR-0022 chose targeted simplification)
- Changing the DAG structure or phase execution model
- Modifying the Redis Streams data plane or observation schema
- Refactoring the Temporal workflow (`claim_verification.py`)
- Adding new agents or changing agent capabilities

## Decisions

### D1. `run_agent_activity` owns all lifecycle, handlers are pure reasoning

**Choice**: Strip START/STOP, heartbeat, and progress from FanoutBase and standalone handlers. The Temporal activity boundary is the single place that wraps agent execution with lifecycle events.

**Alternative considered**: Handler owns lifecycle, activity is a thin pass-through. Rejected because it duplicates the pattern across every handler type and conflicts with the reference pattern's clear separation.

**Implementation**: FanoutBase.run() becomes a slim method that loads upstream context, sets a timeout, and delegates to `_execute()`. Standalone handlers (ingestion-agent, claim-detector, entity-extractor) lose their START/STOP and heartbeat code entirely — the activity wrapper already provides it.

### D2. `load_claim_context()` is a standalone async function

**Choice**: Extract `FanoutBase._load_upstream_context()` into `agents/context.py` as `async def load_claim_context(stream, run_id) -> ClaimContext`. Agents import and call it directly.

**Alternative considered**: Keep it as a FanoutBase method but remove lifecycle from FanoutBase. Rejected because it still forces inheritance for a single utility function.

### D3. `_build_input_message()` template method on LangGraphBase

**Choice**: LangGraphBase._execute() calls `self._build_input_message(context)` to construct the human message. Subclasses override this single method instead of the entire `_execute()`. The canonical `_execute()` in LangGraphBase becomes the only place that constructs `create_react_agent`, instantiates `ChatAnthropic`, suppresses deprecation warnings, and syncs `seq_counter`.

**Alternative considered**: Pass message builder as a constructor argument. Rejected because all agents already use inheritance and a template method is more natural in this class hierarchy.

### D4. Core functions + thin `@tool` facades for dual-use tools

**Choice**: For tools called both programmatically and by LLMs, extract core logic into plain async functions. The `@tool` decorator wraps the core function with LLM-oriented docstrings and `InjectedToolArg` annotations.

**Alternative considered**: Remove `@tool` decorators entirely and call all tools as plain functions. Rejected because LLM-driven agents (coverage-*, synthesizer) genuinely need the `@tool` schema for tool-calling.

### D5. Execution order: bug fix first, then structural changes

S6 (`StreamNotFoundError` fix) ships independently as P0 — it's a one-line import change with no dependencies on other work. Structural changes (S1, S3, S9, S5) follow as P1. P2 items (S2, S4, S7, S8) can be done incrementally.

## Risks / Trade-offs

- **[S1 migration breadth]** Unifying lifecycle touches all 10 agent handlers. → Mitigation: Implement S6 (bug fix) and S5 (dead code deletion) first as confidence builders. Test each agent individually before moving to the next.
- **[S1 dual-publish during migration]** Partially migrated agents may publish START/STOP from both activity and handler. → Mitigation: Migrate all agents in a single commit per pattern group (standalone, FanoutBase, LangGraphBase).
- **[S3 behavioral change in _execute()]** Moving `create_react_agent` construction into a single canonical `_execute()` means subclass-specific model or tool overrides must work through the existing `_model_id()` and `_tools()` hooks. → Mitigation: Verify CoverageHandler, SynthesizerHandler, and BlindspotDetectorHandler don't customize graph construction beyond message content.
- **[S9 orphaned code removal]** Deleting `claimreview_matcher/`, `domain_evidence/`, `blindspot_detector/` directories removes code that may be referenced in tests or documentation. → Mitigation: Grep for all imports and references before deletion.
- **[S4 function count]** Extracting core functions doubles the function count for affected tools. → Trade-off accepted: the duplication is at the API boundary, not in business logic.
