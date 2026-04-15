## ADDED Requirements

### Requirement: Core functions for programmatically-called tools
Tools that are called both programmatically (via handler code) and by LLMs (via LangGraph tool-calling) SHALL have their business logic extracted into plain async functions. The `@tool`-decorated wrapper SHALL be a thin facade that delegates to the core function.

#### Scenario: Programmatic caller uses core function
- **WHEN** `ClaimDetectorHandler` normalizes a claim
- **THEN** it SHALL call `normalize_claim_text(claim_text, ctx)` directly, not `normalize_claim.ainvoke({...})`

#### Scenario: LLM caller uses @tool wrapper
- **WHEN** a LangGraph agent calls the `normalize_claim` tool via tool-calling
- **THEN** the `@tool` wrapper SHALL delegate to `normalize_claim_text()` internally

#### Scenario: No .ainvoke() on @tool in handler code
- **WHEN** searching handler files for `.ainvoke(` calls on `@tool`-decorated functions
- **THEN** zero matches SHALL be found

### Requirement: ToolRuntime removal
The `ToolRuntime` class SHALL be deleted. All code SHALL use `AgentContext` directly.

#### Scenario: No ToolRuntime references in production
- **WHEN** searching the `src/` directory for `ToolRuntime`
- **THEN** zero references SHALL be found

### Requirement: Orphaned handler cleanup
Handler directories for agents no longer in the DAG SHALL be deleted: `claimreview_matcher/`, `domain_evidence/`, `blindspot_detector/`.

#### Scenario: No orphaned registrations
- **WHEN** listing all `@register_handler` decorators in the codebase
- **THEN** every registered handler name SHALL appear in `dag.py`'s `ALL_AGENTS` tuple

#### Scenario: No orphaned directories
- **WHEN** listing directories under `agents/`
- **THEN** `claimreview_matcher/`, `domain_evidence/`, and `blindspot_detector/` SHALL NOT exist
