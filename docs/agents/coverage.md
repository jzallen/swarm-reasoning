# Agent: Coverage

## Overview

| Field | Value |
|-------|-------|
| **Agent ID** | `coverage-left`, `coverage-center`, `coverage-right` |
| **Pipeline Phase** | Phase 2 — Parallel Fan-Out |
| **Pipeline Node** | `pipeline/nodes/coverage.py` |
| **Agent Module** | `agents/coverage/` |
| **Execution Model** | Parameterized factory — 3 instances run concurrently via `asyncio.gather` |
| **Consolidates** | `coverage-left`, `coverage-center`, `coverage-right` |

The coverage agent analyzes how the claim is covered across the political spectrum. A single `create_agent(spectrum, sources)` factory produces three spectrum-parameterized instances that run in parallel. Each searches its spectrum's news sources, detects editorial framing, and selects the highest-credibility source.

## Capabilities

1. **Query construction** — Removes stop words and truncates claim text for search
2. **News search** — Queries NewsAPI filtered to spectrum-specific source lists
3. **Framing detection** — VADER-style headline sentiment analysis classifying coverage as supportive, critical, neutral, or absent
4. **Source ranking** — Selects the highest-credibility source covering the claim

## Tools

| Tool | Description |
|------|-------------|
| `build_search_query()` | Stop-word removal + truncation for NewsAPI query |
| `search_coverage()` | NewsAPI search filtered by spectrum source list |
| `detect_framing()` | Headline sentiment → framing classification (VADER-style) |
| `find_top_source()` | Credibility-ranked source selection |

## Spectrum Parameterization

All three agents share the same tool implementations. The `spectrum` parameter selects the source list:

| Spectrum | Source List | Example Outlets |
|----------|-----------|----------------|
| `left` | `sources/left.json` | MSNBC, The Guardian, HuffPost |
| `center` | `sources/center.json` | Reuters, AP, BBC |
| `right` | `sources/right.json` | Fox News, The Daily Wire, NY Post |

## Input

| Field | Type | Description |
|-------|------|-------------|
| `normalized_claim` | `str` | Normalized claim text from intake |

Typed model: `CoverageInput` in `agents/coverage/models.py`

## Output

| Field | Type | Description |
|-------|------|-------------|
| `article_count` | `int` | Number of articles found |
| `framing` | `str` | Coverage framing (SUPPORTIVE / CRITICAL / NEUTRAL / ABSENT) |
| `top_source` | `str \| None` | Highest-credibility source name |
| `top_source_url` | `str \| None` | URL of top source article |

Typed model: `CoverageOutput` in `agents/coverage/models.py`

The pipeline node collects all three spectrum outputs into `coverage_left`, `coverage_center`, `coverage_right` fields on PipelineState.

## Observation Codes

| Code | Value Type | Description |
|------|-----------|-------------|
| `COVERAGE_ARTICLE_COUNT` | NM | Articles found from this spectrum segment |
| `COVERAGE_FRAMING` | CWE | SUPPORTIVE / CRITICAL / NEUTRAL / ABSENT |
| `COVERAGE_TOP_SOURCE` | ST | Highest-credibility source name |
| `COVERAGE_TOP_SOURCE_URL` | ST | Top source article URL |

The `agent` field in each observation identifies which spectrum agent (coverage-left, coverage-center, or coverage-right) produced it.

## External Dependencies

| Dependency | Purpose | Required Env Var |
|-----------|---------|-----------------|
| NewsAPI | News article search | `NEWSAPI_KEY` |

## Invariants

- **INV-1**: All three spectrum agents run concurrently — no ordering dependency between them.
- **INV-2**: If NewsAPI returns zero results for a spectrum, framing is set to `ABSENT^Not Covered^FCK`.
- **INV-3**: Source lists are static JSON files, not dynamically queried.
- **INV-4**: The coverage node is skipped entirely if `NEWSAPI_KEY` is not configured.
