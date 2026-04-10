## Context

The source-validator is the 11th agent in the swarm-reasoning system, added per ADR-0021. It runs as a Phase 2b agent, dispatched after the five Phase 2a evidence-gathering agents complete. Unlike the Phase 2a agents that query external APIs for new evidence, the source-validator operates on URLs already discovered by other agents. It receives cross-agent observation data as Temporal activity input from the orchestrator workflow. Because the orchestrator dispatches it only after Phase 2a completes, it is guaranteed to receive complete URL data from all evidence-gathering agents.

Key constraints from ADRs and NFRs:
- ADR-0021: Source-Validator Agent -- dedicated agent for link extraction, URL validation, source convergence, citation aggregation
- ADR-0016: Temporal.io orchestration -- agent runs as a Temporal activity worker in the shared agent-service container
- ADR-0004: Tool-based observation construction -- all observations published via the tool layer
- ADR-0011: JSON observation schema -- observations follow the standard schema
- ADR-0003: Append-only observation log -- agent only writes; never modifies existing observations
- ADR-0012: ReasoningStream interface -- transport-agnostic stream access
- ADR-0013: Two communication planes -- Temporal control plane + Redis Streams data plane
- NFR-002: Phase 2 wall-clock latency <= 45 seconds
- NFR-012: External HTTP calls must handle failures gracefully

The agent owns four OBX codes (from obx-code-registry.json):
- `SOURCE_EXTRACTED_URL` (ST): A URL extracted from another agent's content
- `SOURCE_VALIDATION_STATUS` (CWE): Validation result -- LIVE, DEAD, REDIRECT, SOFT404, TIMEOUT
- `SOURCE_CONVERGENCE_SCORE` (NM, 0.0-1.0): Degree of source convergence across agents
- `CITATION_LIST` (TX): JSON-encoded array of citation objects

## Goals / Non-Goals

**Goals:**
- Extract URLs from cross-agent observation data provided as Temporal activity input
- Validate each extracted URL via HTTP HEAD request with redirect following and soft-404 detection
- Compute source convergence score by normalized domain+path matching
- Aggregate validated citations into a structured JSON citation list
- Publish observations to `reasoning:{runId}:source-validator` via ReasoningStream
- Publish progress events to `progress:{runId}` for SSE relay
- Complete within 45-second Phase 2 budget

**Non-Goals:**
- Fetching or parsing full article content (coverage agents do this)
- Modifying other agents' observations
- Deep link analysis (anchor text, link context, PageRank-style scoring)
- Historical URL validation (checking if URLs were live at claim publication date)
- Implementing citation display in the frontend (handled by the frontend slice)

## Decisions

### 1. Cross-agent data access via Temporal activity input

The orchestrator Temporal workflow reads URL-related observations from other agents' streams and passes them as the `cross_agent_data` field of `FanoutActivityInput`. This is consistent with how the blindspot-detector receives coverage data. The source-validator does not read Redis Streams directly for other agents' data.

The `cross_agent_data` dict contains:
```python
{
    "urls": [
        {"url": "https://...", "agent": "coverage-left", "code": "COVERAGE_TOP_SOURCE_URL", "source_name": "Reuters"},
        {"url": "https://...", "agent": "claimreview-matcher", "code": "CLAIMREVIEW_URL", "source_name": "PolitiFact"},
        {"url": "https://...", "agent": "domain-evidence", "code": "DOMAIN_SOURCE_URL", "source_name": "CDC"},
        ...
    ]
}
```

**Alternative considered:** Have the source-validator read all agent streams directly from Redis. Rejected -- violates the principle that cross-agent data access goes through the orchestrator (consistent with blindspot-detector pattern per ADR-0016).

### 2. URL normalization for convergence detection

URLs are normalized before convergence comparison:
1. Parse with `urllib.parse.urlparse`
2. Lowercase the scheme and netloc
3. Strip `www.` prefix from netloc
4. Remove query parameters and fragments
5. Remove trailing slashes from path
6. Reconstruct as `{scheme}://{netloc}{path}`

Example: `https://www.cdc.gov/covid/data/?page=1#section2` normalizes to `https://cdc.gov/covid/data`

This captures the case where coverage-left and domain-evidence both cite the same CDC page but with different query parameters.

### 3. SOURCE_CONVERGENCE_SCORE formula

```python
def compute_convergence_score(extracted_urls: list[ExtractedUrl]) -> float:
    normalized = group_by_normalized_url(extracted_urls)
    if len(normalized) == 0:
        return 0.0
    converging = sum(1 for urls in normalized.values() if len(set(u.agent for u in urls)) >= 2)
    return round(converging / len(normalized), 4)
```

- 0.0: No URLs are cited by multiple agents
- 0.5: Half of unique URLs are cited by 2+ agents
- 1.0: All unique URLs are cited by 2+ agents (perfect convergence)

### 4. Soft-404 detection heuristic

Some servers return HTTP 200 for pages that are effectively 404s. The agent checks the response body (first 2KB) for common soft-404 indicators:
- Page title contains: "page not found", "404", "not found", "no longer available"
- Body contains phrases: "this page doesn't exist", "the page you requested", "has been removed"

If any indicator matches, the URL is classified as SOFT404 rather than LIVE.

### 5. Concurrent URL validation with bounded concurrency

To stay within the 45-second Phase 2 budget, URL validation runs concurrently using `asyncio.Semaphore(10)` to limit concurrent HEAD requests. Each request has a 5-second timeout. With up to ~15 URLs typical (5 agents x ~3 URLs each), validation completes well within the budget.

### 6. CITATION_LIST JSON structure

```json
[
    {
        "sourceUrl": "https://www.politifact.com/factchecks/2023/...",
        "sourceName": "PolitiFact",
        "agent": "claimreview-matcher",
        "observationCode": "CLAIMREVIEW_URL",
        "validationStatus": "live",
        "convergenceCount": 1
    },
    {
        "sourceUrl": "https://www.cdc.gov/covid/data/...",
        "sourceName": "CDC",
        "agent": "domain-evidence",
        "observationCode": "DOMAIN_SOURCE_URL",
        "validationStatus": "live",
        "convergenceCount": 2
    }
]
```

The `convergenceCount` field indicates how many distinct agents cited this normalized source. This JSON is published as the value of the CITATION_LIST observation (TX type).

### 7. Package structure

```
src/
  swarm_reasoning/
    agents/
      source_validator/
        __init__.py
        activity.py          -- SourceValidatorActivity(FanoutActivity): orchestrates 4 capabilities
        extractor.py         -- Link extraction from cross-agent data
        validator.py         -- URL validation via HTTP HEAD
        convergence.py       -- Normalized URL matching, convergence scoring
        aggregator.py        -- Citation list assembly
        models.py            -- ExtractedUrl, ValidationResult, Citation dataclasses
tests/
  unit/
    agents/
      test_source_extractor.py
      test_source_validator.py
      test_source_convergence.py
      test_citation_aggregator.py
  integration/
    agents/
      test_source_validator_flow.py
```

## Risks / Trade-offs

- **[URL validation latency]** -> HTTP HEAD requests can be slow (DNS resolution, TCP handshake, TLS). Mitigated by concurrent requests with 5s per-URL timeout and 10-connection semaphore. Worst case: 15 URLs / 10 concurrency = 2 batches x 5s = 10s.
- **[Soft-404 false positives]** -> The heuristic may misclassify legitimate pages that mention "page not found" in their content. Mitigated by checking the page title first (most reliable indicator) and requiring multiple indicator matches.
- **[Cross-agent data completeness]** -> The orchestrator dispatches source-validator in Phase 2b, after all Phase 2a evidence-gathering agents have completed and emitted STOP. This guarantees that the cross-agent URL data passed to source-validator is complete. No graceful degradation for missing URLs is needed under normal operation.
- **[HEAD request vs GET]** -> Some servers don't support HEAD requests and return 405. The agent falls back to a GET request with a 1KB body limit if HEAD returns 405.
- **[Citation list size]** -> The CITATION_LIST TX observation may be large if many URLs are extracted. Bounded by the practical limit of ~15-20 URLs across 5 evidence-gathering agents. JSON size is well within Redis Streams message limits.
