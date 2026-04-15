## 1. Pipeline Infrastructure (M0)

- [x] 1.1 Create `pipeline/state.py` with PipelineState TypedDict covering all phase inputs/outputs per pipeline-state spec
- [x] 1.2 Create `pipeline/context.py` with PipelineContext dataclass (stream client, run_id, session_id, heartbeat callback, publish_observations method)
- [x] 1.3 Create `pipeline/graph.py` with StateGraph skeleton — placeholder nodes for intake, evidence, coverage, validation, synthesizer; fan-out/fan-in edges; conditional routing for not-check-worthy
- [x] 1.4 Create `activities/run_pipeline.py` with run_langgraph_pipeline Temporal activity wrapping graph invocation with heartbeat callback
- [x] 1.5 Unit tests for PipelineState construction, PipelineContext initialization, graph structure (correct nodes/edges), and activity heartbeat behavior

## 2. Intake Node (M1)

- [x] 2.1 Create `pipeline/nodes/intake.py` with intake_node function and 5 tools (validate_claim, classify_domain, normalize_claim, score_check_worthiness, extract_entities) — port logic from ingestion_agent, claim_detector, entity_extractor handlers
- [x] 2.2 Wire intake_node into pipeline graph replacing placeholder; verify state output populates normalized_claim, claim_domain, check_worthy_score, entities, is_check_worthy
- [x] 2.3 Unit tests: each tool independently, full node with mock LLM, not-check-worthy early exit

## 3. Evidence Node (M2)

- [x] 3.1 Create `pipeline/nodes/evidence.py` with evidence_node function and 4 tools (search_factchecks, derive_evidence_query, fetch_domain_source, score_evidence) — port logic from evidence handler
- [x] 3.2 Wire evidence_node into pipeline graph replacing placeholder; verify fan-out routing dispatches to evidence; verify state output populates claimreview_matches, domain_sources, evidence_confidence
- [x] 3.3 Unit tests: each tool, full node with mock APIs (Google Fact Check, domain sources), graceful degradation when APIs unavailable

## 4. Coverage Node (M3)

- [x] 4.1 Consolidate coverage directory layout: coverage_core.py -> coverage/core.py, coverage_core_tools.py -> coverage/tools.py, 3 sources.json -> coverage/sources/{left,center,right}.json; delete old coverage_left/, coverage_center/, coverage_right/ directories
- [x] 4.2 Create `pipeline/nodes/coverage.py` with coverage_node function and 3 parameterized tools (search_news(spectrum), detect_framing, select_top_source) — read input from PipelineState
- [x] 4.3 Wire coverage_node into pipeline graph; verify fan-out routes to coverage in parallel with evidence; verify state populates coverage_left, coverage_center, coverage_right, framing_analysis
- [x] 4.4 Unit tests: parameterized news search across spectra, framing detection, graceful degradation when NewsAPI unavailable

## 5. Validation Node (M4)

- [x] 5.1 Create `pipeline/nodes/validation.py` with validation_node function and 5 procedural tools (extract_source_urls, validate_urls, compute_convergence, aggregate_citations, analyze_blindspots) — fixed execution order, no LLM routing
- [x] 5.2 Wire validation_node into pipeline graph after fan-in; verify state populates validated_urls, convergence_score, citations, blindspot_score, blindspot_direction
- [x] 5.3 Unit tests: URL extraction/validation, convergence scoring, blindspot analysis with various coverage combinations including missing spectrum

## 6. Synthesizer Node (M5)

- [x] 6.1 Create `pipeline/nodes/synthesizer.py` with synthesizer_node function and 4 tools (resolve_observations, compute_confidence, map_verdict, generate_narrative) — port logic from synthesizer handler
- [x] 6.2 Wire synthesizer_node as terminal node; verify state populates verdict, confidence, narrative, verdict_observations
- [x] 6.3 Unit tests: resolution logic, confidence scoring, verdict mapping thresholds, narrative generation with mock LLM, not-check-worthy bypass

## 7. Graph Composition and Integration (M6)

- [x] 7.1 Implement fan_out_router with Send API: dispatch evidence + coverage in parallel; conditional skip (no NewsAPI key -> skip coverage); not-check-worthy -> skip to synthesizer
- [x] 7.2 Implement fan-in state merge after parallel evidence/coverage; handle partial failures (one node fails, other succeeds)
- [x] 7.3 Add cancellation support: Temporal signal handler propagates to LangGraph via asyncio.Event
- [x] 7.4 Integration test: full pipeline with all nodes, mock LLM and APIs; verify observation publishing to Redis; verify correct PipelineState at each stage

## 8. Temporal Workflow Simplification (M7)

- [ ] 8.1 Rewrite workflows/claim_verification.py with 4-activity pattern (validate_input -> run_pipeline -> persist_verdict -> notify_frontend); register run_langgraph_pipeline; configure timeouts (180s pipeline, 30s heartbeat)
- [ ] 8.2 Update worker.py to register run_langgraph_pipeline instead of individual agent activities; single task queue
- [ ] 8.3 Verify NestJS backend Temporal client starts simplified workflow correctly; ensure session/verdict persistence works with PipelineResult format
- [ ] 8.4 Integration test: full Temporal workflow with LangGraph pipeline activity; verify retry behavior, cancellation signal, frontend notification

## 9. Cleanup (M8)

- [ ] 9.1 Delete old agent handler directories: ingestion_agent/, claim_detector/, entity_extractor/, coverage_left/, coverage_center/, coverage_right/, claimreview_matcher/, domain_evidence/, blindspot_detector/, source_validator/ — preserve evidence/, validation/, synthesizer/ only if tool logic is still referenced by pipeline nodes
- [ ] 9.2 Delete FanoutBase (fanout_base.py), LangGraphBase (langgraph_base.py), ToolRuntime (tool_runtime.py); update all imports
- [ ] 9.3 Delete old DAG (workflows/dag.py), old activity registrations from activities/run_agent.py (keep run_pipeline.py), old worker task queue configuration
- [ ] 9.4 Final verification: run full test suite, grep for orphaned imports, verify no references to deleted modules, verify observation publishing works end-to-end
