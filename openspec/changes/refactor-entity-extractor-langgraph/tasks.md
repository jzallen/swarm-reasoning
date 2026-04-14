## 1. IngestionLangGraphBase

- [ ] 1.1 Create `agents/ingestion_langgraph_base.py` with `IngestionLangGraphBase` class: START/STOP lifecycle (phase=INGESTION), heartbeat loop, progress publishing, internal 30s timeout
- [ ] 1.2 Implement `_load_claim_text(stream, run_id)` — reads `CLAIM_NORMALIZED` from claim-detector stream, raises `StreamNotFoundError` if missing
- [ ] 1.3 Implement `_execute()` — constructs `AgentContext` (with `anthropic_client`), builds `create_react_agent` graph, invokes with normalized claim, syncs `seq_counter` back for STOP message
- [ ] 1.4 Define abstract methods: `_tools()`, `_system_prompt()`, `_primary_code()`, `_model_id()` (with Haiku default)
- [ ] 1.5 Write unit tests for `IngestionLangGraphBase` using a concrete test subclass: verify START/STOP lifecycle, claim loading, timeout behavior

## 2. Entity-Extractor Handler Migration

- [ ] 2.1 Rewrite `handler.py`: `EntityExtractorHandler(IngestionLangGraphBase)` with `AGENT_NAME = "entity-extractor"`
- [ ] 2.2 Implement `_tools()` returning the existing `extract_entities` tool from `tools.py`
- [ ] 2.3 Write system prompt: instruct agent to call `extract_entities` with the normalized claim text
- [ ] 2.4 Implement `_primary_code()` returning `ObservationCode.ENTITY_PERSON` and `_model_id()` returning `claude-haiku-4-5`
- [ ] 2.5 Keep `@register_handler("entity-extractor")` decorator on the new class

## 3. Cleanup

- [ ] 3.1 Remove standalone `_publish_progress`, `_read_normalized_claim`, and `_heartbeat_loop` from `handler.py` (now handled by base class)
- [ ] 3.2 Remove `publisher.py` functions `publish_entities` and `publish_error_stop` (observation publishing is now in `tools.py` via `AgentContext`; keep `normalize_date` since `tools.py` imports it)
- [ ] 3.3 Remove direct Anthropic client construction and `MissingApiKeyError` check from handler `__init__` (base class manages client lifecycle)

## 4. Testing

- [ ] 4.1 Update unit tests in `test_entity_extractor_handler.py`: verify LangGraph agent invocation, START/STOP messages, observation sequence
- [ ] 4.2 Update integration tests in `test_entity_extractor.py`: verify full flow with mocked LLM, observation ordering, progress events
- [ ] 4.3 Test empty extraction: no entities → START + STOP with count=0 and status=F
- [ ] 4.4 Test LLM failure: Anthropic API error → STOP with status=X, error raised for Temporal retry
- [ ] 4.5 Verify `@register_handler` still resolves correctly via `get_agent_handler("entity-extractor")`
