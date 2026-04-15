# Agent: Validation

## Overview

| Field | Value |
|-------|-------|
| **Agent ID** | `validation` |
| **Pipeline Phase** | Phase 3 — Sequential Synthesis |
| **Pipeline Node** | `pipeline/nodes/validation.py` |
| **Agent Module** | `agents/validation/` |
| **Execution Model** | Fixed-order procedural StateGraph (no LLM routing) |
| **Consolidates** | `source-validator`, `blindspot-detector` |

The validation agent is the convergence point after the parallel fan-out. It receives all upstream evidence and coverage data, extracts and validates source URLs, measures how much independent agents converge on the same sources, aggregates citations, and analyzes coverage blindspots across the political spectrum. All five steps execute in fixed order with no LLM decision-making.

## Capabilities

1. **URL extraction** — Extracts source URLs from all upstream agent data
2. **URL validation** — HTTP HEAD requests with soft-404 detection
3. **Convergence analysis** — Measures cross-agent source overlap via normalized domain + path matching
4. **Citation aggregation** — Combines extraction, validation status, and convergence into a unified citation list
5. **Blindspot detection** — Identifies coverage asymmetry across the political spectrum and checks cross-spectrum corroboration

## Tools

| Tool | Module | Description |
|------|--------|-------------|
| `LinkExtractor.extract_urls()` | `source_validator/extractor.py` | Extracts URLs from upstream agent data |
| `UrlValidator.validate_all()` | `source_validator/validator.py` | HTTP HEAD validation with soft-404 detection |
| `ConvergenceAnalyzer.compute()` | `source_validator/convergence.py` | Cross-agent source convergence scoring |
| `CitationAggregator.aggregate()` | `source_validator/aggregator.py` | Unified citation list assembly |
| `compute_blindspot_score()` | `blindspot_detector/analysis.py` | Coverage asymmetry scoring |
| `compute_blindspot_direction()` | `blindspot_detector/analysis.py` | Identifies which spectrum is absent |
| `compute_corroboration()` | `blindspot_detector/analysis.py` | Cross-spectrum consistency check |

## Input

| Field | Type | Description |
|-------|------|-------------|
| `claimreview_matches` | `list` | From evidence agent |
| `domain_sources` | `list` | From evidence agent |
| `coverage_left` | `CoverageOutput` | From coverage-left |
| `coverage_center` | `CoverageOutput` | From coverage-center |
| `coverage_right` | `CoverageOutput` | From coverage-right |

Typed model: `ValidationInput` in `agents/validation/models.py`

## Output

| Field | Type | Description |
|-------|------|-------------|
| `validated_urls` | `list` | URLs with validation status |
| `convergence_score` | `float` | Cross-agent source convergence (0.0–1.0) |
| `citations` | `list` | Aggregated citation objects |
| `blindspot_score` | `float` | Coverage asymmetry (0.0–1.0) |
| `blindspot_direction` | `str` | Which spectrum is absent/underrepresented |

Typed model: `ValidationOutput` in `agents/validation/models.py`

## Observation Codes

| Code | Value Type | Description |
|------|-----------|-------------|
| `SOURCE_EXTRACTED_URL` | ST | Extracted URL (one observation per URL) |
| `SOURCE_VALIDATION_STATUS` | CWE | LIVE / DEAD / REDIRECT / SOFT404 / TIMEOUT |
| `SOURCE_CONVERGENCE_SCORE` | NM | Cross-agent convergence (0.0 = no overlap, 1.0 = full convergence) |
| `CITATION_LIST` | TX | JSON-encoded citation array with URLs, status, origin, convergence |
| `BLINDSPOT_SCORE` | NM | Coverage asymmetry (0.0 = uniform, 1.0 = complete blindspot) |
| `BLINDSPOT_DIRECTION` | CWE | LEFT / RIGHT / CENTER / MULTIPLE / NONE |
| `CROSS_SPECTRUM_CORROBORATION` | CWE | TRUE / FALSE — consistent coverage across all three spectrums |

## External Dependencies

| Dependency | Purpose |
|-----------|---------|
| HTTP HEAD requests | URL liveness validation |

## Invariants

- **INV-1**: All five steps execute in fixed order — no LLM decides the sequence.
- **INV-2**: URL validation uses HTTP HEAD (not GET) to minimize bandwidth.
- **INV-3**: Soft-404 detection checks response body patterns, not just HTTP status codes.
- **INV-4**: Convergence scoring uses normalized domain + path matching, ignoring query parameters and fragments.
- **INV-5**: Blindspot detection reads only coverage agent outputs — it does not re-query news sources.
- **INV-6**: The citation list is consumed by the synthesizer for verdict annotation with source references.
