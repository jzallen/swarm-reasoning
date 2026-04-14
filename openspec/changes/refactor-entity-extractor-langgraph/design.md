## Context

The entity-extractor is a Phase 1 (ingestion) agent that reads `CLAIM_NORMALIZED` from the claim-detector stream, calls Claude Haiku for NER, and publishes `ENTITY_*` observations. It currently uses a bespoke `EntityExtractorHandler` with manual START/STOP lifecycle, heartbeating, and progress management.

Three Phase 2a agents already use `LangGraphBase` (extends `FanoutBase`), which provides a `create_react_agent` graph with tool injection via `AgentContext`. However, `FanoutBase._load_upstream_context()` reads from entity-extractor's own stream — entity-extractor cannot extend `LangGraphBase` without a circular dependency.

A `@tool`-decorated `extract_entities` function already exists in `tools.py` with observation publishing via `AgentContext.publish_obs()`. The migration is primarily about wiring a new base class, not rewriting extraction logic.

## Goals / Non-Goals

**Goals:**
- Create `IngestionLangGraphBase` — a Phase 1 variant of `LangGraphBase` that handles INGESTION phase lifecycle without reading entity-extractor upstream
- Rewrite `EntityExtractorHandler` to extend `IngestionLangGraphBase` and use the existing `extract_entities` tool
- Eliminate bespoke lifecycle code (manual START/STOP, heartbeat loop, progress publishing) from the handler
- Keep `claude-haiku-4-5` as the agent model (entity extraction is focused, low-latency)

**Non-Goals:**
- Changing extraction logic, date normalization, or entity ordering
- Adding new observation types or modifying the OBX code registry
- Migrating ingestion-agent or claim-detector to LangGraph (future work)
- Modifying `FanoutBase` or `LangGraphBase` — the new base class is additive
- Changing the Temporal workflow DAG or phase structure

## Decisions

### D1: New `IngestionLangGraphBase` rather than modifying `FanoutBase`

**Decision**: Create `agents/ingestion_langgraph_base.py` as a standalone base class that mirrors `LangGraphBase`'s ReAct agent pattern but manages Phase 1 lifecycle.

**Rationale**: `FanoutBase._load_upstream_context()` reads from entity-extractor, creating a circular dependency. Modifying `FanoutBase` to conditionally skip upstream reads would muddy the Phase 1 vs Phase 2a separation. A dedicated base class keeps the phase boundary clean and can be reused if ingestion-agent or claim-detector are later migrated.

**Alternative considered**: Have entity-extractor use LangGraph directly in the handler without a base class. Rejected because it would duplicate the START/STOP, heartbeat, and progress boilerplate that a base class eliminates.

### D2: `IngestionLangGraphBase` reads only from claim-detector

**Decision**: The base class provides `_load_claim_text(stream, run_id)` which reads `CLAIM_NORMALIZED` from the claim-detector stream. No entity-extractor or ingestion-agent context loading.

**Rationale**: Entity-extractor only needs the normalized claim as input. Phase 1 agents have simpler upstream dependencies than Phase 2a agents — the base class should reflect this.

### D3: Reuse existing `extract_entities` tool from `tools.py`

**Decision**: The handler's `_tools()` method returns the existing `extract_entities` tool. No new tool code is written.

**Rationale**: The tool already implements observation publishing via `AgentContext.publish_obs()`, maintains deterministic entity ordering, and handles date normalization. It was designed for exactly this LangGraph migration.

### D4: `claude-haiku-4-5` as agent model

**Decision**: Override `_model_id()` to return `claude-haiku-4-5`. The default `LangGraphBase` model is Sonnet.

**Rationale**: Entity extraction is a single-tool, single-step task. Haiku is sufficient for the routing decision ("call extract_entities with the claim text") and keeps latency and cost low. The actual NER call inside the tool also uses Haiku.

### D5: Inject `AsyncAnthropic` client via `AgentContext`

**Decision**: Pass the Anthropic client through `AgentContext.anthropic_client` so the `extract_entities` tool can use it for the NER LLM call.

**Rationale**: The tool already accepts `anthropic_client` as an `InjectedToolArg`. The base class constructs `AgentContext` with the client, matching the existing injection pattern.

## Risks / Trade-offs

- **[Risk] Double LLM call** — The LangGraph agent makes one LLM call to decide which tool to call, then the tool makes a second LLM call for NER. This doubles the LLM cost for entity extraction. → **Mitigation**: Both calls use Haiku (cheapest model). The routing call is trivial (~100 tokens). Total cost increase is negligible vs the consistency benefit.

- **[Risk] Phase 1 timeout sensitivity** — Phase 1 has a 30s `start_to_close` timeout. Adding LangGraph routing overhead could push edge cases past the limit. → **Mitigation**: Haiku routing adds <1s. The existing handler already operates well within the 30s budget. The base class uses the same 30s internal timeout as `FanoutBase`.

- **[Risk] `IngestionLangGraphBase` code duplication** — The new base class duplicates some lifecycle logic from `FanoutBase` (heartbeat, progress, START/STOP). → **Mitigation**: The overlap is small (~50 lines). Extracting a shared mixin would add complexity for minimal gain. If a third Phase 1 agent is migrated, revisit.
