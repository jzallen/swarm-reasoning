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
- [ ] 1.6 Delete existing unit tests for normalizer and scorer

---

## S2: Rename and Refactor domain_cls.py

- [ ] 2.1 Rename `agents/intake/tools/domain_cls.py` → `agents/intake/tools/domain_classification.py`
- [ ] 2.2 Update all imports referencing `domain_cls` to `domain_classification`
- [ ] 2.3 Delete `call_claude()` function from `domain_classification.py` — no longer needed
- [ ] 2.4 Delete `_SYSTEM_PROMPT` and `_RETRY_SUFFIX` constants (prompt moves to tool closure)
- [ ] 2.5 Keep `DOMAIN_VOCABULARY` and `build_prompt()` as module exports

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

---

## S5: Implement decompose_claims Tool

- [ ] 5.1 Create `agents/intake/tools/decompose_claims.py` with `Citation`, `ExtractedClaim`, and `DecomposeResult` models
- [ ] 5.2 Implement system prompt for claim extraction (up to 5 claims: claim_text, quote, citation)
- [ ] 5.3 Implement `decompose_claims_llm()` function: ChatAnthropic.ainvoke with config forwarding
- [ ] 5.4 Implement output parsing: JSON parse, field validation (claim_text, quote, citation with publisher), truncation to 5
- [ ] 5.5 Implement retry on JSON parse failure (one retry, then NO_FACTUAL_CLAIMS)
- [ ] 5.6 Add `get_stream_writer()` progress events
- [ ] 5.7 Add `decompose_claims` tool definition in `agent.py` with model via closure

---

## S6: Update Agent Builder

- [ ] 6.1 Update `build_intake_agent()`: create sub-model instances for each tool
- [ ] 6.2 Define tools as closures capturing their respective models
- [ ] 6.3 Update TOOLS list: `[fetch_content, decompose_claims, classify_domain, extract_entities]`
- [ ] 6.4 Update SYSTEM_PROMPT for new workflow: fetch → decompose → (user selects) → classify → extract
- [ ] 6.5 Update `IntakeOutput` model in `models.py` for URL-based flow (extracted claims, selected claim)
- [ ] 6.6 Replace `create_react_agent` with `create_agent`

---

## S7: Update Pipeline Node

- [ ] 7.1 Update `pipeline/nodes/intake.py` for two-phase interaction (Phase A: URL→claims, Phase B: selection→analysis)
- [ ] 7.2 Update PipelineState translation for new IntakeOutput fields
- [ ] 7.3 Implement `get_stream_writer()` → Redis progress translation in node wrapper
- [ ] 7.4 Update observation publishing for new flow (CLAIM_TEXT from selected claim, not raw input)

---

## S8: Update claim_intake.py

- [ ] 8.1 Remove `ingest_claim` function and `IngestionResult` model (replaced by fetch_content)
- [ ] 8.2 Keep `validate_source_url()` and `normalize_date()` as utility exports (used by fetch_content)
- [ ] 8.3 Remove `check_duplicate()` — dedup moves to pipeline level with URL-based keying
- [ ] 8.4 Remove `StreamPublishError`, `StreamNotOpenError` — pipeline node handles errors
- [ ] 8.5 Update `__init__.py` exports

---

## S9: Integration Tests

Test the compiled intake agent graph as a whole using `FakeListChatModel` for
deterministic LLM responses. Mock HTTP at the httpx transport layer. Focus on
behavior, invariants, and side-effects — not internal construction.

### Fixtures

- [ ] 9.1 Create `conftest.py` with `@pytest.fixture(scope="module")` for compiled intake graph using `FakeListChatModel`
- [ ] 9.2 Create httpx mock transport fixture returning canned HTML responses (news article, opinion piece, 404, non-HTML)
- [ ] 9.3 Create helper to build `FakeListChatModel` with canned tool-call responses for each test scenario

### Happy Path: URL → Claims → Selection → Analysis

- [ ] 9.4 Valid news URL produces 1-5 claims, each with `claim_text`, `quote`, and `citation` (citation has `publisher`)
- [ ] 9.5 After claim selection, agent produces domain classification from `DOMAIN_VOCABULARY` and entity extraction result
- [ ] 9.6 Full flow state contains: fetched article text, extracted claims, selected claim, domain, entities
- [ ] 9.7 Progress events are emitted via `stream_mode="custom"` at each tool boundary (fetch, decompose, classify, extract)

### Rejection Paths: Agent Stops Early on Bad Input

- [ ] 9.8 Invalid URL format → agent returns error, no HTTP request made, no LLM calls made
- [ ] 9.9 Unreachable URL (HTTP 404/500/timeout) → agent returns error with `URL_UNREACHABLE`, no LLM calls made
- [ ] 9.10 Non-HTML content type → agent returns error with `URL_NOT_HTML`
- [ ] 9.11 Page with < 50 words of content → agent returns error with `CONTENT_TOO_SHORT`
- [ ] 9.12 Opinion article with no factual claims → agent returns `NO_FACTUAL_CLAIMS`, no classify/extract calls made

### Invariants

- [ ] 9.13 No tool imports or instantiates `AsyncAnthropic` — grep assertion across `agents/intake/tools/`
- [ ] 9.14 All LLM sub-calls receive `RunnableConfig` — verified by `FakeListChatModel` callback tracking
- [ ] 9.15 `decompose_claims` never returns more than 5 claims, even if LLM response contains more
- [ ] 9.16 Every `citation` in returned claims has a non-empty `publisher` field
- [ ] 9.17 `quote` field in each claim is a substring of the original article text (exact match check)

### Side-Effect Handling

- [ ] 9.18 HTTP fetch uses 10s timeout — mock transport that sleeps verifies `TimeoutException` is caught
- [ ] 9.19 Trafilatura extraction failure falls back to BeautifulSoup, then to error — not an unhandled exception
- [ ] 9.20 Malformed LLM JSON on first decompose attempt triggers one retry, then `NO_FACTUAL_CLAIMS` — not a crash
- [ ] 9.21 Domain classification with unrecognized LLM response falls back to `OTHER` after 2 attempts

### State Transition Assertions

- [ ] 9.22 Phase A output: PipelineState contains `extracted_claims` list and `article_text`, but no `domain` or `entities`
- [ ] 9.23 Phase B output: PipelineState contains `selected_claim`, `domain`, `entities`, plus all Phase A fields
- [ ] 9.24 Rejected input: PipelineState contains `error` field, no claim or analysis fields populated
