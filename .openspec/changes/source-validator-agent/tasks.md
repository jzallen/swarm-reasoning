## 1. Package Setup and Data Models

- [x] 1.1 Create `src/swarm_reasoning/agents/source_validator/` package with `__init__.py`
- [x] 1.2 Create module files: `activity.py`, `extractor.py`, `validator.py`, `convergence.py`, `aggregator.py`, `models.py`
- [x] 1.3 Implement dataclasses in `models.py`: ExtractedUrl (url, agent, observation_code, source_name), ValidationResult (url, status, final_url, error), Citation (source_url, source_name, agent, observation_code, validation_status, convergence_count)
- [x] 1.4 Define ValidationStatus enum: LIVE, DEAD, REDIRECT, SOFT404, TIMEOUT
- [x] 1.5 Implement Citation.to_dict() for JSON serialization
- [x] 1.6 Write unit tests for model dataclasses: construction, serialization, enum values

## 2. Link Extraction

- [x] 2.1 Create `extractor.py` with `LinkExtractor` class
- [x] 2.2 Implement `extract_urls(cross_agent_data)`: parse URLs list from Temporal activity input, construct ExtractedUrl objects, deduplicate by exact URL preserving all agent associations
- [x] 2.3 Implement URL filtering: reject non-HTTP/HTTPS, localhost, private IPs; log warnings for skipped URLs
- [x] 2.4 Handle empty/malformed input gracefully (empty list, no error)
- [x] 2.5 Write unit tests: full extraction (5 agents, ~15 URLs), deduplication, empty data, malformed URL, localhost rejection

## 3. URL Validation

- [x] 3.1 Create `validator.py` with `UrlValidator` class
- [x] 3.2 Implement `validate_url(url)`: HTTP HEAD via httpx with 5s timeout, follow redirects up to 5 hops; classify as LIVE/DEAD/REDIRECT/TIMEOUT
- [x] 3.3 Implement soft-404 detection: on HTTP 200, fetch first 2KB of body, check for "page not found", "404", "not found" in title/body
- [x] 3.4 Implement HEAD->GET fallback: retry with GET on HTTP 405
- [x] 3.5 Implement `validate_all(urls)`: concurrent validation via asyncio.gather with Semaphore(10)
- [x] 3.6 Write unit tests: HTTP 200->LIVE, 404->DEAD, 301->REDIRECT, timeout->TIMEOUT, soft-404 detection, HEAD 405 fallback
- [x] 3.7 Write unit test: concurrent validation of 15 URLs with semaphore bounding

## 4. Source Convergence

- [x] 4.1 Create `convergence.py` with `ConvergenceAnalyzer` class
- [x] 4.2 Implement `normalize_url(url)`: lowercase scheme+netloc, strip www., remove query/fragment/trailing slash
- [x] 4.3 Implement `compute_convergence_score(extracted)`: count normalized URLs cited by 2+ agents / total unique, round to 4 places
- [x] 4.4 Implement `get_convergence_count(url, groups)`: distinct agent count for a normalized URL
- [x] 4.5 Write unit tests: normalization (www strip, query removal, case), convergence scoring (0, partial, full, empty list, single URL)

## 5. Citation Aggregation

- [x] 5.1 Create `aggregator.py` with `CitationAggregator` class
- [x] 5.2 Implement `aggregate(extracted, validations, convergence_groups)`: combine into Citation objects, one per (url, agent, code) tuple
- [x] 5.3 Implement `to_citation_list_json(citations)`: serialize to sorted JSON array
- [x] 5.4 Handle missing validation: set validationStatus to "not-validated"
- [x] 5.5 Write unit tests: full aggregation, JSON round-trip, missing validation fallback, multi-agent expansion

## 6. Source Validator Activity

- [x] 6.1 Create `activity.py` with `SourceValidatorActivity(FanoutActivity)`
- [x] 6.2 Implement `_execute()`: extract -> validate -> compute convergence -> aggregate -> publish observations
- [x] 6.3 Publish SOURCE_EXTRACTED_URL observations (one per URL, ST, F-status)
- [x] 6.4 Publish SOURCE_VALIDATION_STATUS observations (one per URL, CWE, F-status)
- [x] 6.5 Publish SOURCE_CONVERGENCE_SCORE observation (single NM, F-status)
- [x] 6.6 Publish CITATION_LIST observation (single TX with JSON array, F-status)
- [x] 6.7 Publish progress events: "Validating source URLs...", "Validated {n}/{total} URLs", "Aggregated {n} source citations"
- [x] 6.8 Handle empty input: convergence 0.0, empty citation list, STOP finalStatus=F
- [x] 6.9 Implement internal timeout (30s): publish partial results, set remaining to TIMEOUT, STOP finalStatus=X

## 7. Temporal Activity Registration

- [x] 7.1 Register `run_source_validator` activity in activities.py with @activity.defn
- [x] 7.2 Configure: start_to_close_timeout=45s, retry_policy max_attempts=3
- [ ] 7.3 Update orchestrator to pass cross-agent URL data in FanoutActivityInput.cross_agent_data
- [ ] 7.4 Write unit test: activity importable with correct decorator

## 8. Integration Tests

- [x] 8.1 Write full integration test: mock HTTP -> 10 URLs -> verify all 4 observation types in stream
- [x] 8.2 Integration test: 3 agents cite same URL -> convergence > 0.0, convergenceCount = 3
- [x] 8.3 Integration test: mix of live, dead, soft-404 URLs -> correct validation statuses
- [x] 8.4 Integration test: empty input -> convergence 0.0, empty citation list, STOP F
- [x] 8.5 Integration test: CITATION_LIST JSON is valid and matches Citation schema
- [x] 8.6 Integration test: progress events in progress:{runId}, execution time <= 45s
