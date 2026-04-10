---
status: accepted
date: 2026-04-10
deciders: []
---

# ADR-0021: Source-Validator Agent

## Context and Problem Statement

The existing 10 agents gather evidence from Google Fact Check API, NewsAPI, and domain-specific sources, but none of them extract links from retrieved content, validate that cited URLs are accessible, or check for source convergence across agents. The synthesizer produces a verdict but the API response only includes a "top source" per coverage spectrum -- there is no consolidated, annotated source list. Link rot degrades trust in results, and source convergence (multiple agents citing the same underlying source) is a strong signal for confidence scoring that is currently unused.

## Decision Drivers

- Users need to see which sources informed the verdict with working links
- Link rot degrades trust in results: dead URLs undermine credibility
- Source convergence across agents is a strong signal for confidence scoring
- Current design only surfaces "top source" per coverage spectrum, not a full citation list

## Considered Options

1. **Add source validation to existing agents** -- Distribute link extraction and URL validation across the coverage agents and domain-evidence agent. Each agent would need HTTP validation logic, and citation aggregation still requires a central collection point. Violates single-responsibility and duplicates validation code.
2. **Dedicated source-validator agent** -- An 11th agent with single responsibility for link extraction, URL validation, source convergence detection, and citation aggregation. Runs in parallel with other Phase 2 agents. Clean ownership of citation-related observation codes.
3. **Post-synthesis validation** -- Run source validation after the synthesizer emits its verdict. Catches dead links but cannot inform confidence scoring because the verdict is already final.

## Decision Outcome

Chosen option: "Dedicated source-validator agent", because it maintains single responsibility per agent, runs in parallel during Phase 2 (no additional latency on the critical path), and its citation list output directly feeds the synthesizer's verdict annotation and confidence scoring.

The source-validator agent performs four functions:

1. **Link extraction** -- Scans retrieved article content and fact-check responses from other agents' observation streams for cited URLs.
2. **URL validation** -- Checks that extracted URLs are live via HEAD requests, follows redirects, and detects soft 404s (pages that return 200 but contain "page not found" content).
3. **Source convergence** -- Identifies when multiple agents cite the same underlying source (by normalized domain + path), producing a convergence score that strengthens confidence.
4. **Citation aggregation** -- Publishes a structured citation list observation that the synthesizer uses to build the annotated source list in the verdict.

New observation codes owned by source-validator:

- `SOURCE_EXTRACTED_URL` -- A URL extracted from agent content
- `SOURCE_VALIDATION_STATUS` -- Validation result for an extracted URL (live, dead, redirect, soft-404)
- `SOURCE_CONVERGENCE_SCORE` -- Convergence metric for sources cited by multiple agents
- `CITATION_LIST` -- Aggregated, annotated citation list for the synthesizer

The agent reads observations from other agents' streams via the orchestrator Temporal workflow, which provides cross-agent stream data as activity input (consistent with the blindspot-detector's access pattern).

### Consequences

- Good, because the verdict response includes a consolidated citation list with validation status for each source
- Good, because URL validation catches dead sources before they reach users
- Good, because convergence scoring provides an additional signal for the synthesizer's confidence calculation
- Bad, because adding an 11th Temporal activity worker increases the container count and resource footprint
- Bad, because HTTP HEAD requests for URL validation add latency to Phase 2 (mitigated by parallel execution and timeouts)
- Neutral, because source-validator reads other agents' streams via the orchestrator Temporal workflow, consistent with the existing blindspot-detector access model

## More Information

- ADR-0016: Temporal.io for Agent Orchestration (orchestrator provides cross-agent stream data)
- ADR-0011: JSON Observation Schema (observation code ownership)
- ADR-0013: Two Communication Planes (observation publication via Redis Streams data plane)
- Observation code registry: `docs/domain/obx-code-registry.json`
