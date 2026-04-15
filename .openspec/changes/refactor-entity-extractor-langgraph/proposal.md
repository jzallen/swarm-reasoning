## Why

The entity-extractor is the last Phase 1 agent still using a bespoke handler pattern. The three other agents that have migrated to LangGraph (claimreview-matcher, coverage agents, blindspot-detector) gained consistent lifecycle management, tool-based observation publishing, and cleaner testability. Converting entity-extractor completes the LangGraph migration for all agents that make LLM calls, eliminates the manual START/STOP/heartbeat boilerplate in `handler.py`, and enables the LLM to reason about entity disambiguation and date normalization rather than applying rigid post-processing rules.

## What Changes

- Replace `EntityExtractorHandler` with a LangGraph ReAct agent that uses tools to extract and publish entities
- Convert `extract_entities_llm()` and `publish_entities()` into LangChain `@tool` functions that publish observations via `AgentContext`
- Introduce an `IngestionLangGraphBase` class for Phase 1 agents — `LangGraphBase` extends `FanoutBase` which reads entity-extractor's own output, making it unsuitable for Phase 1 agents
- Remove the manual `_heartbeat_loop`, `_publish_progress`, and START/STOP lifecycle code from entity-extractor
- Keep `claude-haiku-4-5` as the model (entity extraction is a focused, low-latency task)

## Capabilities

### New Capabilities

- `entity-extractor-agent`: LangGraph ReAct agent with entity extraction tools and Phase 1 lifecycle base class, replacing the current procedural handler.

### Modified Capabilities

_(none — same 5 ENTITY_* observation codes published, same extraction logic, same stream protocol)_

## Impact

- **Modified package**: `agents/entity_extractor/` — `handler.py` rewritten, `extractor.py` and `publisher.py` logic moved into tools
- **New module**: `agents/ingestion_langgraph_base.py` — Phase 1 variant of `LangGraphBase` (reads from claim-detector only, publishes with INGESTION phase)
- **Tests**: Unit and integration tests updated for LangGraph agent invocation pattern
- **No workflow changes**: Entity-extractor remains in Phase 1 sequential pipeline; `ClaimVerificationWorkflow` and `DAG` are untouched
- **No observation schema changes**: Same codes, same value types, same stream key format
