# Tasks -- intake-redesign

## Prerequisites

- [x] Existing intake agent is functional (agents/intake/)
- [ ] `trafilatura` added to agent-service pyproject.toml dependencies

---

## S1: Cleanup — Delete Obsolete Tools

- [ ] 1.1 Delete `agents/intake/tools/normalizer.py`
- [ ] 1.2 Delete `agents/intake/tools/scorer.py`
- [ ] 1.3 Remove `normalize_claim` and `score_check_worthiness` tool definitions from `agent.py`
- [ ] 1.4 Remove imports of `normalize_claim_text` and `score_claim_text` from `agent.py`
- [ ] 1.5 Update system prompt in `agent.py` to remove steps 3 (normalize) and 4 (score)
- [ ] 1.6 Delete unit tests for normalizer and scorer (find and remove)
- [ ] 1.7 Verify remaining tests pass after deletion

---

## S2: Rename and Refactor domain_cls.py

- [ ] 2.1 Rename `agents/intake/tools/domain_cls.py` → `agents/intake/tools/domain_classification.py`
- [ ] 2.2 Update all imports referencing `domain_cls` to `domain_classification`
- [ ] 2.3 Delete `call_claude()` function from `domain_classification.py` — no longer needed
- [ ] 2.4 Delete `_SYSTEM_PROMPT` and `_RETRY_SUFFIX` constants (prompt moves to tool closure)
- [ ] 2.5 Keep `DOMAIN_VOCABULARY` and `build_prompt()` as module exports
- [ ] 2.6 Update unit tests for domain classification imports

---

## S3: Standardize LLM Sub-call Pattern

- [ ] 3.1 Add model constants to `agent.py`: `AGENT_MODEL`, `DECOMPOSE_MODEL`, `CLASSIFY_MODEL`, `ENTITY_MODEL`
- [ ] 3.2 Delete `_get_anthropic_client()` from `agent.py`
- [ ] 3.3 Refactor `classify_domain` tool: accept `config: RunnableConfig`, use `ChatAnthropic` via closure
- [ ] 3.4 Refactor `extract_entities` tool: accept `config: RunnableConfig`, use `ChatAnthropic` via closure
- [ ] 3.5 Remove `model_id` default parameter from `extract_entities_llm()` in `entity_extractor.py`
- [ ] 3.6 Remove `"Do not infer or hallucinate."` from entity extraction system prompt
- [ ] 3.7 Replace `create_react_agent` with `create_agent` in `agent.py`
- [ ] 3.8 Verify no tool directly imports `AsyncAnthropic` or `anthropic` (grep check)
- [ ] 3.9 Update unit tests for new tool signatures (config parameter)

---

## S4: Implement fetch_content Tool

- [ ] 4.1 Add `trafilatura` and `httpx` to agent-service pyproject.toml
- [ ] 4.2 Create `agents/intake/tools/fetch_content.py` with `fetch_content_from_url()` function
- [ ] 4.3 Implement URL format validation (regex `^https?://[^\s]+\.[^\s]{2,}$`)
- [ ] 4.4 Implement async HTTP GET with httpx (10s timeout, User-Agent header)
- [ ] 4.5 Implement content extraction: trafilatura → BeautifulSoup fallback → error
- [ ] 4.6 Implement title extraction from trafilatura metadata or `<title>` tag
- [ ] 4.7 Implement date extraction from trafilatura metadata, normalize to YYYYMMDD
- [ ] 4.8 Implement word count check (minimum 50 words)
- [ ] 4.9 Add `get_stream_writer()` progress events
- [ ] 4.10 Add `fetch_content` tool definition in `agent.py` (no LLM sub-call, pure I/O)
- [ ] 4.11 Write unit tests: valid URL, invalid format, unreachable, non-HTML, too short, extraction fallback

---

## S5: Implement decompose_claims Tool

- [ ] 5.1 Create `agents/intake/tools/decompose_claims.py` with `Citation`, `ExtractedClaim`, and `DecomposeResult` models
- [ ] 5.2 Implement system prompt for claim extraction (up to 5 claims: claim_text, quote, citation)
- [ ] 5.3 Implement `decompose_claims_llm()` function: ChatAnthropic.ainvoke with config forwarding
- [ ] 5.4 Implement output parsing: JSON parse, field validation (claim_text, quote, citation with publisher), truncation to 5
- [ ] 5.5 Implement retry on JSON parse failure (one retry, then NO_FACTUAL_CLAIMS)
- [ ] 5.6 Add `get_stream_writer()` progress events
- [ ] 5.7 Add `decompose_claims` tool definition in `agent.py` with model via closure
- [ ] 5.8 Write unit tests: successful extraction, opinion article, short article, malformed LLM response

---

## S6: Update Agent Builder

- [ ] 6.1 Update `build_intake_agent()`: create sub-model instances for each tool
- [ ] 6.2 Define tools as closures capturing their respective models
- [ ] 6.3 Update TOOLS list: `[fetch_content, decompose_claims, classify_domain, extract_entities]`
- [ ] 6.4 Update SYSTEM_PROMPT for new workflow: fetch → decompose → (user selects) → classify → extract
- [ ] 6.5 Update `IntakeOutput` model in `models.py` for URL-based flow (extracted claims, selected claim)
- [ ] 6.6 Replace `create_react_agent` with `create_agent`
- [ ] 6.7 Write unit tests for agent builder: tool list, model configuration, system prompt content

---

## S7: Update Pipeline Node

- [ ] 7.1 Update `pipeline/nodes/intake.py` for two-phase interaction (Phase A: URL→claims, Phase B: selection→analysis)
- [ ] 7.2 Update PipelineState translation for new IntakeOutput fields
- [ ] 7.3 Implement `get_stream_writer()` → Redis progress translation in node wrapper
- [ ] 7.4 Update observation publishing for new flow (CLAIM_TEXT from selected claim, not raw input)
- [ ] 7.5 Write unit tests for pipeline node: Phase A output, Phase B output, progress translation

---

## S8: Update claim_intake.py

- [ ] 8.1 Remove `ingest_claim` function and `IngestionResult` model (replaced by fetch_content)
- [ ] 8.2 Keep `validate_source_url()` and `normalize_date()` as utility exports (used by fetch_content)
- [ ] 8.3 Remove `check_duplicate()` — dedup moves to pipeline level with URL-based keying
- [ ] 8.4 Remove `StreamPublishError`, `StreamNotOpenError` — pipeline node handles errors
- [ ] 8.5 Update `__init__.py` exports
- [ ] 8.6 Update tests for reduced module scope

---

## S9: Integration Tests

- [ ] 9.1 Integration test: valid URL → fetch → decompose → 5 claims returned
- [ ] 9.2 Integration test: invalid URL → error response with URL_INVALID_FORMAT
- [ ] 9.3 Integration test: unreachable URL → error response with URL_UNREACHABLE
- [ ] 9.4 Integration test: opinion article → NO_FACTUAL_CLAIMS
- [ ] 9.5 Integration test: full flow — URL → claims → user selects → classify + extract → observations in stream
- [ ] 9.6 Integration test: progress events emitted via get_stream_writer and translated to Redis
