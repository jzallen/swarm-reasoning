# ADR-0023: LangGraph Pipeline — Implementation Beads

Bead graph created 2026-04-14. 42 beads (9 epics + 33 tasks) across M0-M8, 5 dependency layers.

| Epic | Bead ID | Tasks | Layer | Depends On |
|------|---------|-------|-------|------------|
| M0: Pipeline Infrastructure | sr-4me | 5 | 0 | — |
| M1: Intake Node | sr-e2k | 3 | 1 | M0 |
| M2: Evidence Node | sr-501 | 3 | 1 | M0 |
| M3: Coverage Node | sr-yzd | 4 | 1 | M0 |
| M4: Validation Node | sr-3kw | 3 | 1 | M0 |
| M5: Synthesizer Node | sr-c37 | 3 | 1 | M0 |
| M6: Graph Composition | sr-0tw | 4 | 2 | M1-M5 |
| M7: Temporal Simplification | sr-etq | 4 | 3 | M6 |
| M8: Cleanup | sr-qi2 | 4 | 4 | M7 |

## M0: Pipeline Infrastructure [epic] P1

Pipeline skeleton: PipelineState TypedDict, PipelineContext (Redis client, run_id, observation publisher), graph skeleton with placeholder nodes, heartbeat callback, and the `run_langgraph_pipeline` Temporal activity wrapper.

### M0.1: Define PipelineState TypedDict P1

Create `services/agent-service/src/swarm_reasoning/pipeline/state.py` with the PipelineState TypedDict covering all phase inputs/outputs as defined in ADR-0023.

### M0.2: Define PipelineContext P1

Create `services/agent-service/src/swarm_reasoning/pipeline/context.py` with PipelineContext dataclass (Redis client, run_id, session_id, stream interface, observation publisher, heartbeat callback).

### M0.3: Create graph skeleton with placeholder nodes P1

Create `services/agent-service/src/swarm_reasoning/pipeline/graph.py` with StateGraph definition, placeholder nodes (intake, evidence, coverage, validation, synthesizer), fan-out/fan-in edges, and conditional routing for not-check-worthy claims.

### M0.4: Create run_langgraph_pipeline Temporal activity P1

Create `services/agent-service/src/swarm_reasoning/activities/run_pipeline.py` wrapping the LangGraph graph invocation with Temporal heartbeat integration and observation-to-Redis publishing.

### M0.5: Unit tests for pipeline infrastructure P1

Tests for PipelineState construction, PipelineContext initialization, graph structure validation (correct nodes and edges), and activity wrapper heartbeat behavior.

## M1: Intake Node [epic] P1

Consolidate ingestion-agent + claim-detector + entity-extractor into a single intake graph node with 5 tools: validate_claim, classify_domain, normalize_claim, score_check_worthiness, extract_entities.

### M1.1: Create intake node with 5 tools P1

Create `services/agent-service/src/swarm_reasoning/pipeline/nodes/intake.py` implementing the intake_node function. Port tool logic from existing handlers (ingestion_agent, claim_detector, entity_extractor). Use ReAct agent internally or fixed tool execution order.

### M1.2: Wire intake node into pipeline graph P1

Replace placeholder intake node in graph.py with real intake_node. Verify state output populates normalized_claim, claim_domain, check_worthy_score, entities, is_check_worthy.

### M1.3: Unit tests for intake node P1

Test each tool function independently. Test the full node with mock LLM. Test not-check-worthy early exit.

## M2: Evidence Node [epic] P1

Port the committed evidence agent (claimreview-matcher + domain-evidence) into a pipeline graph node with 4 tools: search_factchecks, derive_evidence_query, fetch_domain_source, score_evidence.

### M2.1: Create evidence node with 4 tools P1

Create `services/agent-service/src/swarm_reasoning/pipeline/nodes/evidence.py`. Port tool logic from the existing evidence handler. Read input from PipelineState instead of Redis streams.

### M2.2: Wire evidence node into pipeline graph P1

Replace placeholder evidence node. Verify fan-out routing dispatches to evidence node. Verify state output populates claimreview_matches, domain_sources, evidence_confidence.

### M2.3: Unit tests for evidence node P1

Test each tool. Test full node with mock APIs (Google Fact Check, domain sources). Test graceful degradation when APIs are unavailable.

## M3: Coverage Node [epic] P1

Port the coverage consolidation (3 spectrum agents → 1) into a pipeline graph node with 3 parameterized tools: search_news(spectrum), detect_framing, select_top_source.

### M3.1: Consolidate coverage directory layout P1

Move coverage_core.py → coverage/core.py, coverage_core_tools.py → coverage/tools.py. Consolidate 3 sources.json files into coverage/sources/{left,center,right}.json. Delete old coverage_left/, coverage_center/, coverage_right/ directories. (From dave: consolidate-coverage-directory)

### M3.2: Create coverage node with parameterized tools P1

Create `services/agent-service/src/swarm_reasoning/pipeline/nodes/coverage.py`. Implement search_news(spectrum) that iterates over all 3 spectra. Read input from PipelineState.

### M3.3: Wire coverage node into pipeline graph P1

Replace placeholder. Verify fan-out routes to coverage in parallel with evidence. Verify state output populates coverage_left, coverage_center, coverage_right, framing_analysis.

### M3.4: Unit tests for coverage node P1

Test parameterized news search across spectra. Test framing detection. Test graceful degradation when NewsAPI unavailable.

## M4: Validation Node [epic] P1

Port the committed validation agent (source-validator + blindspot-detector) into a pipeline graph node with 5 procedural tools: extract_source_urls, validate_urls, compute_convergence, aggregate_citations, analyze_blindspots.

### M4.1: Create validation node with 5 tools P1

Create `services/agent-service/src/swarm_reasoning/pipeline/nodes/validation.py`. Port tool logic from existing validation handler. Fixed execution order (no LLM routing). Read from PipelineState.

### M4.2: Wire validation node into pipeline graph P1

Replace placeholder. Position after fan-in (evidence + coverage complete). Verify state output populates validated_urls, convergence_score, citations, blindspot_score, blindspot_direction.

### M4.3: Unit tests for validation node P1

Test URL extraction and validation. Test convergence scoring. Test blindspot analysis with various coverage combinations.

## M5: Synthesizer Node [epic] P1

Port the synthesizer to a pipeline graph node with 4 tools: resolve_observations, compute_confidence, map_verdict, generate_narrative. This is the only node with genuine LLM reasoning for verdict decisions.

### M5.1: Create synthesizer node with 4 tools P1

Create `services/agent-service/src/swarm_reasoning/pipeline/nodes/synthesizer.py`. Port logic from existing synthesizer (resolver, scorer, mapper, narrator). Read all upstream data from PipelineState.

### M5.2: Wire synthesizer node into pipeline graph P1

Replace placeholder. Position as terminal node. Verify state output populates verdict, confidence, narrative, verdict_observations.

### M5.3: Unit tests for synthesizer node P1

Test resolution logic. Test confidence scoring. Test verdict mapping thresholds. Test narrative generation with mock LLM.

## M6: Graph Composition and Integration [epic] P1

Connect all nodes into the complete pipeline graph. Implement fan-out/fan-in with LangGraph Send API. Add conditional routing (not-check-worthy bypass, missing API key handling). Integration test the full pipeline.

### M6.1: Implement fan-out routing with Send API P1

Implement fan_out_router that dispatches to evidence and coverage in parallel. Handle conditional skip (no NewsAPI key → skip coverage). Handle not-check-worthy → skip to synthesizer.

### M6.2: Implement fan-in state merge P1

Implement state merge after parallel evidence/coverage completion. Handle partial failures (one node fails, other succeeds).

### M6.3: Add cancellation support P1

Add Temporal signal handler for cancellation. Propagate cancellation to LangGraph graph via asyncio.Event. From dave: workflow-resilience (cancellation concept).

### M6.4: Integration test full pipeline P1

End-to-end test with all nodes, mock LLM and APIs. Verify observation publishing to Redis. Verify correct PipelineState at each stage.

## M7: Temporal Workflow Simplification [epic] P1

Replace the DAG-driven multi-activity workflow with the simplified 4-activity workflow: validate_input → run_pipeline → persist_verdict → notify_frontend.

### M7.1: Create simplified ClaimVerificationWorkflow P1

Rewrite workflows/claim_verification.py with the 4-activity pattern from ADR-0023. Register run_langgraph_pipeline as an activity. Configure timeouts (180s pipeline, 30s heartbeat).

### M7.2: Update worker registration P1

Update worker.py to register the new activity (run_langgraph_pipeline) instead of individual agent activities. Single task queue.

### M7.3: Update NestJS backend for simplified workflow P1

Verify backend's Temporal client starts the simplified workflow correctly. Ensure session/verdict persistence works with new result format.

### M7.4: Integration test simplified workflow P1

Test the full Temporal workflow with the LangGraph pipeline activity. Verify retry behavior, cancellation signal, and frontend notification.

## M8: Cleanup [epic] P2

Delete old infrastructure: individual agent handler directories, FanoutBase, LangGraphBase per-agent base class, DAG definition, dead code from ADR-0022 S5/S9/S10.

### M8.1: Delete old agent handler directories P2

Remove agents/ingestion_agent/, agents/claim_detector/, agents/entity_extractor/, agents/coverage_left/, agents/coverage_center/, agents/coverage_right/, agents/claimreview_matcher/, agents/domain_evidence/, agents/blindspot_detector/, agents/source_validator/. Preserve agents/evidence/ and agents/validation/ and agents/synthesizer/ only if they still contain shared tool logic referenced by pipeline nodes.

### M8.2: Delete FanoutBase and LangGraphBase P2

Remove agents/fanout_base.py and agents/langgraph_base.py. Remove agents/tool_runtime.py (ToolRuntime). Update all imports.

### M8.3: Delete old DAG and workflow infrastructure P2

Remove workflows/dag.py. Remove old activity registrations from activities/run_agent.py (keep run_pipeline.py). Remove old worker task queue configuration.

### M8.4: Final verification P2

Run full test suite. Grep for orphaned imports. Verify no references to deleted modules. Verify observation publishing works end-to-end.
