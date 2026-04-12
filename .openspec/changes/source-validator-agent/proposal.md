## Why

The existing 10 agents gather evidence from Google Fact Check API, NewsAPI, and domain-specific sources, but none of them extract links from retrieved content, validate that cited URLs are accessible, or check for source convergence across agents. The synthesizer produces a verdict but the API response only includes a "top source" per coverage spectrum -- there is no consolidated, annotated source list. Link rot degrades trust in results, and source convergence (multiple agents citing the same underlying source) is a strong signal for confidence scoring that is currently unused. Per ADR-0021, a dedicated source-validator agent addresses all four gaps.

## What Changes

- Implement `source-validator` as a Temporal activity worker in the shared agent-service container (ADR-0016)
- Implement link extraction: scan other agents' observation streams for cited URLs (COVERAGE_TOP_SOURCE_URL, CLAIMREVIEW_URL, DOMAIN_SOURCE_URL, and any other URL-typed observations)
- Implement URL validation: HTTP HEAD requests with redirect following, soft-404 detection (200 status but "page not found" content), timeout handling
- Implement source convergence scoring: normalized domain+path matching to detect when multiple agents cite the same underlying source. Produce SOURCE_CONVERGENCE_SCORE (0.0-1.0)
- Implement citation aggregation: publish CITATION_LIST -- JSON array of citation objects with sourceUrl, sourceName, agent, observationCode, validationStatus, convergenceCount
- The agent receives cross-agent observation data as Temporal activity input (the orchestrator workflow reads other agents' streams and passes the data)
- Publish observations to `reasoning:{runId}:source-validator` via the ReasoningStream interface
- Publish progress events to `progress:{runId}` for SSE relay

## Capabilities

### New Capabilities

- `link-extraction`: Scans cross-agent observation data for URL-typed values. Extracts URLs from COVERAGE_TOP_SOURCE_URL (3 agents), CLAIMREVIEW_URL, DOMAIN_SOURCE_URL, and any SOURCE_EXTRACTED_URL from other agents. Deduplicates by normalized URL. Publishes one SOURCE_EXTRACTED_URL observation per unique URL found.
- `url-validation`: Validates each extracted URL via HTTP HEAD request. Detects live (200), dead (4xx/5xx), redirect (3xx final location), soft-404 (200 with "page not found" content heuristic), and timeout. Publishes one SOURCE_VALIDATION_STATUS observation per URL.
- `source-convergence`: Computes convergence score by normalizing URLs to domain+path (stripping query params, fragments, trailing slashes) and counting how many distinct agents cite each normalized source. Score = (URLs cited by 2+ agents) / (total unique URLs). Publishes SOURCE_CONVERGENCE_SCORE as a single NM observation.
- `citation-aggregation`: Aggregates all extracted URLs with their validation status, originating agent, observation code, and convergence count into a JSON array. Publishes CITATION_LIST as a single TX observation consumed by the synthesizer for verdict annotation.

### Modified Capabilities

None -- this is a new agent with no prior implementation.

## Impact

- **New package**: `src/swarm_reasoning/agents/source_validator/` (Python)
- **No new containers**: Agent runs as a Temporal activity worker in the shared agent-service container (ADR-0016)
- **Observation codes**: Owns 4 new codes in obx-code-registry.json: SOURCE_EXTRACTED_URL, SOURCE_VALIDATION_STATUS, SOURCE_CONVERGENCE_SCORE, CITATION_LIST
- **Depends on**: Cross-agent observation data provided as Temporal activity input by the orchestrator workflow. Requires other Phase 2 agents to have published their URL observations (orchestrator reads streams before dispatching source-validator or provides data concurrently)
- **Downstream impact**: Synthesizer reads SOURCE_CONVERGENCE_SCORE as a confidence signal and CITATION_LIST for verdict annotation. Blindspot-detector reads SOURCE_CONVERGENCE_SCORE as additional input.
- **NFR-002**: Phase 2 agent -- must complete within 45 seconds. URL validation is the bottleneck; mitigated by concurrent HEAD requests with per-URL timeout of 5 seconds.
