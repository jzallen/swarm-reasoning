## Why

The agent-service has a five-layer execution stack (Temporal activity -> FanoutBase -> LangGraphBase -> handler -> tools) where inter-agent data flows through Redis Streams, requiring each of 11 agents to manage its own stream lifecycle. ADR-0022 identified 12 structural issues (S1-S12) in this layering. ADR-0023 determined that patching these issues individually preserves the root cause: each agent is a separate Temporal activity with inter-agent Redis coupling. A monolithic LangGraph pipeline — one StateGraph running inside one Temporal activity — eliminates this coupling structurally rather than patching around it.

Emma and dave have already consolidated 11 agents down to 5 (intake, evidence, coverage, validation, synthesizer). These 5 map directly to pipeline graph nodes.

## What Changes

- **New LangGraph pipeline**: One `StateGraph` with 5 nodes (intake, evidence, coverage, validation, synthesizer) replacing the multi-activity DAG-driven Temporal workflow
- **PipelineState TypedDict**: Typed state object replaces Redis Streams as the inter-node data plane; observations still published to Redis as side-effects for SSE
- **PipelineContext**: Shared runtime context (Redis client, heartbeat callback, observation publisher) passed via LangGraph RunnableConfig
- **Simplified Temporal workflow**: 4 activities (validate_input -> run_pipeline -> persist_verdict -> notify_frontend) replacing the ~200-line DAG orchestrator
- **Fan-out/fan-in via LangGraph Send API**: Parallel evidence + coverage execution with conditional routing (skip coverage if no NewsAPI key, skip to synthesizer if not check-worthy)
- **Single activity heartbeat**: Pipeline nodes update heartbeat detail with current phase, replacing 4 duplicated heartbeat loops
- **BREAKING**: Old per-agent Temporal activities removed; worker registration changes from individual agent activities to single pipeline activity
- **Cleanup**: Delete FanoutBase, LangGraphBase, per-agent handler directories, DAG definition, ToolRuntime

## Capabilities

### New Capabilities
- `pipeline-state`: PipelineState TypedDict and PipelineContext dataclass — the typed data plane and runtime context for the monolithic pipeline
- `intake-node`: Consolidated intake graph node (ingestion + claim-detector + entity-extractor) with 5 tools: validate_claim, classify_domain, normalize_claim, score_check_worthiness, extract_entities
- `evidence-node`: Evidence graph node (claimreview-matcher + domain-evidence) with 4 tools: search_factchecks, derive_evidence_query, fetch_domain_source, score_evidence
- `coverage-node`: Coverage graph node (coverage-left/center/right consolidated) with 3 parameterized tools: search_news(spectrum), detect_framing, select_top_source
- `validation-node`: Validation graph node (source-validator + blindspot-detector) with 5 procedural tools: extract_source_urls, validate_urls, compute_convergence, aggregate_citations, analyze_blindspots
- `synthesizer-node`: Synthesizer graph node with 4 tools: resolve_observations, compute_confidence, map_verdict, generate_narrative
- `graph-composition`: Pipeline graph assembly — fan-out/fan-in edges, conditional routing, cancellation support, observation publishing
- `temporal-simplification`: Simplified 4-activity Temporal workflow replacing the DAG-driven multi-activity orchestrator

### Modified Capabilities

## Impact

- **Agent service (Python)**: All agent handler directories replaced by `pipeline/nodes/`. FanoutBase, LangGraphBase, DAG, ToolRuntime deleted. New `pipeline/` package with state.py, context.py, graph.py, and nodes/ subdirectory.
- **Temporal workflow**: `workflows/claim_verification.py` rewritten from ~200 lines to ~30 lines. Worker registers one activity instead of 11.
- **NestJS backend**: Minimal changes — workflow name and result format may need updates.
- **Redis Streams**: Still used for observation publishing (SSE continuity). No longer used for inter-agent data reads.
- **Frontend**: No changes — SSE relay continues to work via Redis observation streams.
- **Tests**: All per-agent handler tests replaced by per-node tests. Integration test validates full pipeline.
