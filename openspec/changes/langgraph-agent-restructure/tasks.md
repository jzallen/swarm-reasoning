## 1. Integration Test Infrastructure

- [ ] 1.1 Create `tests/integration/pipeline/conftest.py` with async Redis fixture (connects to localhost:6379), unique run_id generator, and PipelineContext factory using real RedisReasoningStream
- [ ] 1.2 Add `@pytest.mark.integration` marker to `pyproject.toml` and configure pytest to skip integration tests when Redis is unavailable
- [ ] 1.3 Create `tests/fixtures/observation_manifest.json` mapping all 36 OBX codes to owning pipeline node, expected agent identity, value type, and mandatory/conditional status

## 2. Per-Node Integration Tests

- [ ] 2.1 Create `tests/integration/pipeline/test_intake_integration.py` — run intake_node with real Redis, verify CLAIM_TEXT, CLAIM_DOMAIN, CHECK_WORTHY_SCORE, CLAIM_NORMALIZED, and entity observations are published to `reasoning:{run_id}:ingestion-agent`
- [ ] 2.2 Create `tests/integration/pipeline/test_evidence_integration.py` — run evidence_node with real Redis and mocked Fact Check API, verify CLAIMREVIEW_MATCH, CLAIMREVIEW_VERDICT, CLAIMREVIEW_SOURCE, DOMAIN_SOURCE_NAME observations
- [ ] 2.3 Create `tests/integration/pipeline/test_coverage_integration.py` — run coverage_node with real Redis and mocked NewsAPI, verify COVERAGE_ARTICLE_COUNT, COVERAGE_FRAMING, COVERAGE_TOP_SOURCE for all 3 spectrums
- [ ] 2.4 Create `tests/integration/pipeline/test_validation_integration.py` — run validation_node with real Redis, verify SOURCE_EXTRACTED_URL, SOURCE_VALIDATION_STATUS, SOURCE_CONVERGENCE_SCORE, CITATION_LIST, BLINDSPOT_SCORE, BLINDSPOT_DIRECTION
- [ ] 2.5 Create `tests/integration/pipeline/test_synthesizer_integration.py` — run synthesizer_node with real Redis, verify CONFIDENCE_SCORE, VERDICT, VERDICT_NARRATIVE observations with status F

## 3. Full-Pipeline Integration Test

- [ ] 3.1 Create `tests/integration/pipeline/test_full_pipeline.py` — invoke `pipeline_graph.ainvoke()` with real PipelineContext, check-worthy claim, mocked external APIs; verify final state has verdict, confidence, narrative
- [ ] 3.2 Add not-check-worthy routing test — verify pipeline routes directly from intake to synthesizer when claim is not check-worthy
- [ ] 3.3 Add observation completeness assertion — load manifest, verify all mandatory codes are emitted in Redis streams for the check-worthy test case
- [ ] 3.4 Add observation sequence assertion — verify synthesizer observations have timestamps after validation observations

## 4. Observation Manifest Verification

- [ ] 4.1 Create `tests/unit/test_observation_manifest.py` — unit test that loads the manifest and compares against `_CODE_METADATA` registry, failing if codes are missing or stale
- [ ] 4.2 Add conditional-code documentation to manifest — mark coverage codes as conditional on NewsAPI key, document skip conditions

## 5. Temporal Workflow Completion

- [ ] 5.1 Create `activities/validate_input.py` — validate_input activity that checks claim_text non-empty and session_id format, raises non-retryable ApplicationError on invalid input
- [ ] 5.2 Create `activities/persist_verdict.py` — persist_verdict activity that stores PipelineResult (verdict, confidence, narrative) to run status store via update_run_status
- [ ] 5.3 Create `activities/notify_frontend.py` — notify_frontend activity that publishes VERDICT_READY event to `progress:{run_id}` Redis stream for SSE relay
- [ ] 5.4 Update `workflows/claim_verification.py` to call 4 activities in sequence: validate_input → run_langgraph_pipeline → persist_verdict → notify_frontend
- [ ] 5.5 Update `worker.py` to register validate_input, persist_verdict, and notify_frontend activities
- [ ] 5.6 Add unit tests for validate_input, persist_verdict, and notify_frontend activities
- [ ] 5.7 Add workflow unit test verifying 4-activity sequence with mocked activities

## 6. ADR and Spec Finalization

- [ ] 6.1 Update ADR-0023 status from `proposed` to `accepted`, add "Decision Outcome" section documenting measured results (node count reduction, test coverage, heartbeat simplification)
- [ ] 6.2 Archive stale openspec change `simplify-langgraph-temporal-layering` (all 42 tasks obsolete — code was deleted wholesale)
- [ ] 6.3 Archive stale openspec change `refactor-entity-extractor-langgraph` (entity extraction now in intake node)
- [ ] 6.4 Check off remaining pipeline-migration tasks (M8.1-M8.3, M9.1-M9.3) that were completed by recent refactoring commits

## 7. Final Verification

- [ ] 7.1 Run full unit test suite — all existing tests pass
- [ ] 7.2 Run integration test suite against Docker Compose Redis — all new tests pass
- [ ] 7.3 Grep for orphaned imports referencing deleted modules (FanoutBase, LangGraphBase, ToolRuntime, run_agent, dag)
- [ ] 7.4 Verify NestJS backend Temporal client can start the updated workflow and parse PipelineResult
