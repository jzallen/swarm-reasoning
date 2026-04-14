## 1. Bug Fix: StreamNotFoundError Duplication (P0)

- [ ] 1.1 Delete `class StreamNotFoundError` from `fanout_base.py:51` and replace with `from swarm_reasoning.agents._utils import StreamNotFoundError`
- [ ] 1.2 Verify `NON_RETRYABLE_ERRORS` in `run_agent.py` catches the now-unified class
- [ ] 1.3 Add unit test: FanoutBase raising StreamNotFoundError is caught as non-retryable by run_agent_activity

## 2. Dead Code Removal

- [ ] 2.1 Delete `ToolRuntime` class from `agents/tool_runtime.py`
- [ ] 2.2 Update `tests/unit/agents/test_tool_runtime.py` to remove ToolRuntime references
- [ ] 2.3 Update `tests/unit/agents/test_observation_tools.py` to remove ToolRuntime references
- [ ] 2.4 Delete orphaned `agents/claimreview_matcher/` directory
- [ ] 2.5 Delete orphaned `agents/domain_evidence/` directory
- [ ] 2.6 Delete orphaned `agents/blindspot_detector/` directory
- [ ] 2.7 Grep for all imports referencing deleted modules and fix or remove them

## 3. Shared Heartbeat Utility

- [ ] 3.1 Add `heartbeat_loop()` function to `agents/_utils.py` (extracted from existing implementations)
- [ ] 3.2 Replace `_heartbeat_loop` in `fanout_base.py` with import from `_utils`
- [ ] 3.3 Replace `_heartbeat_loop` in `ingestion_agent/handler.py` with import from `_utils`
- [ ] 3.4 Replace `_heartbeat_loop` in `claim_detector/handler.py` with import from `_utils`
- [ ] 3.5 Replace `_heartbeat_loop` in `entity_extractor/handler.py` with import from `_utils`

## 4. Unify Stream Lifecycle Ownership

- [ ] 4.1 Verify `run_agent_activity` publishes START/STOP, heartbeat, and progress for all agent types (audit current behavior)
- [ ] 4.2 Remove START/STOP publishing from `FanoutBase.run()`
- [ ] 4.3 Remove heartbeat loop from `FanoutBase.run()`
- [ ] 4.4 Remove progress publishing from `FanoutBase.run()`
- [ ] 4.5 Rename `FanoutBase.run()` to `FanoutBase.execute()` — now just upstream context + timeout + delegate to `_execute()`
- [ ] 4.6 Remove START/STOP and heartbeat from `ingestion_agent/handler.py`
- [ ] 4.7 Remove START/STOP and heartbeat from `claim_detector/handler.py`
- [ ] 4.8 Remove START/STOP and heartbeat from `entity_extractor/handler.py`
- [ ] 4.9 Update `run_agent_activity` to call `handler.execute()` instead of `handler.run()` for FanoutBase handlers
- [ ] 4.10 Add integration test: each agent type produces exactly one START and one STOP in its stream

## 5. Fix _publish_progress Abstraction Leak

- [ ] 5.1 Add `publish_progress(key, data)` method to `ReasoningStream` interface
- [ ] 5.2 Implement `publish_progress()` in `RedisReasoningStream`
- [ ] 5.3 Update `run_agent.py:_publish_progress()` to use `_stream_client.publish_progress()` instead of `_stream_client._redis.xadd()`

## 6. Extract Upstream Context Loading

- [ ] 6.1 Create `agents/context.py` with `async def load_claim_context(stream, run_id) -> ClaimContext`
- [ ] 6.2 Move logic from `FanoutBase._load_upstream_context()` into `load_claim_context()`
- [ ] 6.3 Update all FanoutBase subclasses to call `load_claim_context()` directly (coverage-*, source-validator, validation, domain-evidence, synthesizer)
- [ ] 6.4 Remove `_load_upstream_context()` from `FanoutBase`
- [ ] 6.5 Add unit test for `load_claim_context()` with mock streams

## 7. LangGraphBase Template Method Hook

- [ ] 7.1 Add `_build_input_message(self, context: ClaimContext) -> str` method to `LangGraphBase` with default `_format_claim_input()` behavior
- [ ] 7.2 Update `LangGraphBase._execute()` to call `self._build_input_message(context)` for human message construction
- [ ] 7.3 Replace `CoverageHandler._execute()` override with `_build_input_message()` override that appends source IDs/JSON
- [ ] 7.4 Replace `SynthesizerHandler._execute()` override with `_build_input_message()` override
- [ ] 7.5 Replace `BlindspotDetectorHandler._execute()` override with `_build_input_message()` override (if still present after S9 orphan removal — verify first)
- [ ] 7.6 Verify no handler files contain `create_react_agent` calls except `langgraph_base.py`

## 8. Core Function Extraction for Programmatic Tools

- [ ] 8.1 Extract `normalize_claim_text()` from `claim_detector/tools/normalize.py`, keep `@tool normalize_claim` as thin wrapper
- [ ] 8.2 Extract `score_check_worthiness_core()` from `claim_detector/tools/score.py`, keep `@tool` wrapper
- [ ] 8.3 Extract core functions from `source_validator/tools/` (extract_urls, validate_urls, compute_convergence, aggregate_citations)
- [ ] 8.4 Extract core functions from `validation/tools/` (compute_convergence_score, analyze_blindspots)
- [ ] 8.5 Update `claim_detector/handler.py` to call core functions instead of `.ainvoke()`
- [ ] 8.6 Update `source_validator/handler.py` to call core functions instead of `.ainvoke()`
- [ ] 8.7 Update `validation/handler.py` to call core functions instead of `.ainvoke()`
- [ ] 8.8 Verify no handler files call `.ainvoke()` on `@tool`-decorated functions

## 9. Verification

- [ ] 9.1 Run full test suite — all existing tests pass
- [ ] 9.2 Grep: exactly one `class StreamNotFoundError` definition exists
- [ ] 9.3 Grep: exactly one `create_react_agent` invocation in handler code
- [ ] 9.4 Grep: zero `.ainvoke(` calls on `@tool` functions in handler code
- [ ] 9.5 Grep: exactly one `_heartbeat_loop` definition exists
- [ ] 9.6 Grep: zero references to `ToolRuntime` in `src/`
- [ ] 9.7 Grep: all `@register_handler` names appear in `dag.py` `ALL_AGENTS`
