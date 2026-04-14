## Why

The agent-service has grown additional abstraction layers between LangGraph (reasoning) and Temporal (durability) that duplicate lifecycle management, scatter identical code across files, and include a latent bug where `StreamNotFoundError` class duplication causes Temporal to retry stream-not-found errors indefinitely instead of failing fast. ADR-0022 documents 12 findings and prescribes 9 concrete simplifications.

## What Changes

- **Unify stream lifecycle ownership**: `run_agent_activity` becomes the single owner of START/STOP, heartbeat, and progress events. FanoutBase and standalone handlers stop managing lifecycle.
- **Extract upstream context loading**: Move `_load_upstream_context()` from FanoutBase into a standalone function. Agents call it directly instead of inheriting FanoutBase for context access.
- **Add `_build_input_message()` hook**: Replace 4 near-identical `_execute()` overrides (CoverageHandler, SynthesizerHandler, BlindspotDetectorHandler, LangGraphBase) with a single template method hook for message customization.
- **Extract core logic from `@tool` wrappers**: Split programmatically-called tools into core async functions + thin `@tool` facades, so procedural agents skip LangChain's invoke machinery.
- **Fix `StreamNotFoundError` duplication** (bug): Delete local class in `fanout_base.py`, import from `_utils` so Temporal's `NON_RETRYABLE_ERRORS` catches it.
- **Delete `ToolRuntime`**: Remove dead production code (only used in tests).
- **Extract shared `_heartbeat_loop`**: Deduplicate identical static methods across 4 files into `_utils.py`.
- **Fix `_publish_progress` abstraction leak**: Stop accessing `_stream_client._redis` directly; add proper method to `ReasoningStream` interface.
- **Remove orphaned handler directories**: Delete `claimreview_matcher/`, `domain_evidence/`, `blindspot_detector/` — unreachable via DAG after consolidation.

## Capabilities

### New Capabilities
- `unified-lifecycle`: Stream lifecycle (START/STOP, heartbeat, progress) owned exclusively by `run_agent_activity`, with handlers responsible only for reasoning logic
- `context-loading`: Standalone `load_claim_context()` function replacing FanoutBase's bundled context + lifecycle approach
- `langgraph-template-method`: `_build_input_message()` hook on LangGraphBase enabling message customization without `_execute()` duplication
- `tool-core-extraction`: Plain async functions for programmatic tool callers, with `@tool` wrappers as thin LLM-facing facades

### Modified Capabilities

## Impact

- **Agent service (Python)**: All 10 agent handlers are touched. FanoutBase shrinks significantly. LangGraphBase gains a hook method. 3 handler directories are deleted.
- **Temporal retry behavior**: S6 bug fix changes error handling for stream-not-found from indefinite retry to immediate non-retryable failure.
- **Transport abstraction (ADR-012)**: S8 removes direct Redis access in `_publish_progress`, restoring the `ReasoningStream` interface contract.
- **Tests**: Unit tests for ToolRuntime are deleted. Integration tests for lifecycle (START/STOP ordering) may need updates to reflect single-layer publishing.
