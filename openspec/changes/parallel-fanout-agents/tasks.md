## 1. FanoutActivity Shared Base Class

- [ ] 1.1 Create `src/swarm_reasoning/agents/fanout_base.py` with `FanoutActivity` ABC: `__init__(input)`, `_load_upstream_context()`, `_execute()` abstract, `run()` entry point (START -> execute -> STOP)
- [ ] 1.2 Define `FanoutActivityInput` dataclass: `run_id`, `claim_id`, `cross_agent_data` (optional, used by source-validator)
- [ ] 1.3 Define `FanoutActivityResult` dataclass: `status` ("COMPLETED"|"CANCELLED"), `observation_count`, `error_reason`
- [ ] 1.4 Implement `_load_upstream_context()`: reads CLAIM_NORMALIZED, CLAIM_DOMAIN, and ENTITY_* from upstream streams via ReasoningStream, populates `ClaimContext` dataclass
- [ ] 1.5 Implement `publish_observation` tool: validates code ownership per obx-code-registry.json, constructs ObsMessage via Pydantic, publishes to stream (ADR-0004)
- [ ] 1.6 Implement `publish_progress` helper: publishes user-friendly events to `progress:{runId}` for SSE relay (ADR-0018)
- [ ] 1.7 Implement configurable execution timeout (default 30s) via `asyncio.wait_for`; on timeout publish X-status STOP
- [ ] 1.8 Implement START/STOP message emission with proper message format
- [ ] 1.9 Write unit tests: context loading, timeout enforcement, observation validation rejection, START/STOP format

## 2. Temporal Activity Registration

- [ ] 2.1 Create `src/swarm_reasoning/agents/activities.py` registering all Phase 2 activities with `@activity.defn`
- [ ] 2.2 Register activities: run_claimreview_matcher, run_coverage_left, run_coverage_center, run_coverage_right, run_domain_evidence
- [ ] 2.3 Register run_source_validator stub (implementation in source-validator slice)
- [ ] 2.4 Configure activity options: start_to_close_timeout=45s, retry_policy with max_attempts=3, non_retryable for API key errors
- [ ] 2.5 Write unit test: all five Phase 2a activity functions importable with correct decorators (source-validator stub registered for Phase 2b)

## 3. ClaimReview Matcher Agent

- [ ] 3.1 Create `src/swarm_reasoning/agents/claimreview_matcher/` package with `__init__.py` and `activity.py`
- [ ] 3.2 Implement `_build_query(context)`: combine CLAIM_NORMALIZED with top entity names (max 100 chars)
- [ ] 3.3 Implement `_call_api(query)`: async GET to Google Fact Check Tools API, handle 429 with 1 retry after 2s
- [ ] 3.4 Implement `_score_matches(results, claim_normalized)`: TF-IDF cosine similarity, return best match above 0.50 threshold
- [ ] 3.5 Implement `_execute()`: API call -> score -> publish observations (5 on match, 2 on no-match); publish progress events; handle ApiError gracefully
- [ ] 3.6 Write unit tests: query building, match scoring thresholds (>=0.75, 0.50-0.75, <0.50), full match path, no-match path, API error path
- [ ] 3.7 Write integration test: mock API -> full run -> assert observations and progress events

## 4. Coverage Agents (Left / Center / Right)

- [ ] 4.1 Create source fixture files: `coverage_left/sources.json`, `coverage_center/sources.json`, `coverage_right/sources.json` with source IDs and credibility ranks
- [ ] 4.2 Create packages: `coverage_left/`, `coverage_center/`, `coverage_right/` each with `__init__.py` and `activity.py` as thin wrappers
- [ ] 4.3 Create `src/swarm_reasoning/agents/coverage_core.py` with shared `CoverageAgentCore` logic
- [ ] 4.4 Implement `_build_search_query(context)`: remove stop words, truncate to 100 chars at word boundary
- [ ] 4.5 Implement `_call_newsapi(query, sources)`: async GET to NewsAPI /v2/everything, handle 429 with 1 retry after 1s
- [ ] 4.6 Implement `_detect_framing(articles)`: VADER sentiment on top 5 headlines, map to SUPPORTIVE/CRITICAL/NEUTRAL/ABSENT
- [ ] 4.7 Implement `_select_top_source(articles, sources)`: rank by credibility, return (name, url)
- [ ] 4.8 Implement `_execute()`: API -> framing -> top source -> publish 4 observations (or 2 if 0 articles); progress events
- [ ] 4.9 Write unit tests: query building, framing detection (all 4 outcomes), top source selection, API error handling
- [ ] 4.10 Write integration test: mock NewsAPI -> run all three concurrently -> assert independent streams, observation counts

## 5. Domain Evidence Agent

- [ ] 5.1 Create `src/swarm_reasoning/agents/domain_evidence/` package with `__init__.py`, `activity.py`, `routes.json`
- [ ] 5.2 Implement `_derive_query(context)`: prepend entity names, append statistics, truncate to 80 chars
- [ ] 5.3 Implement `_fetch_source(url_template, query)`: httpx with 10s timeout, follow redirects, return content or None
- [ ] 5.4 Implement `_is_relevant(content, context)`: entity/keyword presence in title/heading (BeautifulSoup)
- [ ] 5.5 Implement `_score_alignment(content, context)`: keyword overlap + negation detection -> SUPPORTS/CONTRADICTS/PARTIAL/ABSENT
- [ ] 5.6 Implement `_score_confidence(alignment, fallback_depth, source_age, is_indirect)`: penalty factors, floor at 0.10/0.0
- [ ] 5.7 Implement `_execute()`: routing table iteration (max 2 attempts), fetch, score, publish 4 observations with N/A placeholders for ABSENT; progress events
- [ ] 5.8 Write unit tests: query derivation, alignment scoring (all 4 outcomes), confidence penalty accumulation, ABSENT floor
- [ ] 5.9 Write unit tests for HTTP resilience: 404 fallback, 5xx retry, all sources fail -> ABSENT
- [ ] 5.10 Write integration test: mock HTTP -> full run -> 4 observations, correct STOP

## 6. LangChain Agent Integration

- [ ] 6.1 Implement LangChain agent wrapper in FanoutActivity for LLM-driven reasoning steps
- [ ] 6.2 Define agent-specific LangChain tools for each of the 5 agents (search, score, publish)
- [ ] 6.3 Configure LangChain agents with Anthropic Claude model
- [ ] 6.4 Write unit tests: verify tool invocation order per agent type

## 7. Observation Schema Validation

- [ ] 7.1 Implement code ownership, value type, and CWE format validation in publish_observation
- [ ] 7.2 Implement auto-incrementing seq numbering within agent stream
- [ ] 7.3 Write unit tests: ownership rejection, value type validation, CWE format, seq numbering

## 8. Integration Tests: Full Phase 2 Fan-Out

- [ ] 8.1 Write `tests/integration/agents/test_fanout_phase.py`: mock all APIs -> dispatch five Phase 2a agents via Temporal -> assert all five streams have STOP messages -> then dispatch source-validator in Phase 2b
- [ ] 8.2 Verify Phase 2a wall-clock <= 45s (NFR-002) against mocked APIs
- [ ] 8.3 One agent fails (X-status) while four complete (F-status) -> partial results preserved, Phase 2b still runs
- [ ] 8.4 Temporal activity retry: simulate transient failure, verify success on retry
- [ ] 8.5 Progress events from all six agents (5 Phase 2a + 1 Phase 2b) appear in `progress:{runId}` stream

## 9. Environment Configuration

- [ ] 9.1 Define env var requirements: GOOGLE_FACTCHECK_API_KEY, NEWSAPI_KEY, REDIS_URL, TEMPORAL_HOST
- [ ] 9.2 Implement graceful degradation when API keys missing: X-status observations, WARNING logs
- [ ] 9.3 Write unit tests: missing API keys produce X-status, do not raise
