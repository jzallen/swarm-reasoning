# Agent: Intake

## Overview

| Field | Value |
|-------|-------|
| **Agent ID** | `intake` |
| **Pipeline Phase** | Phase 1 — Sequential Ingestion |
| **Pipeline Node** | `pipeline/nodes/intake.py` |
| **Agent Module** | `agents/intake/` |
| **Execution Model** | Fixed-order procedural (no LLM tool selection) |
| **Consolidates** | `ingestion-agent`, `claim-detector`, `entity-extractor` |

The intake agent is the pipeline entry point. It validates the submitted claim, classifies its domain, normalizes the text for downstream matching, scores check-worthiness, and extracts named entities. All five steps execute in fixed order — no LLM routing.

## Capabilities

1. **Claim ingestion** — Validates claim text, source URL, and publication date
2. **Domain classification** — LLM-based classification into controlled vocabulary (HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER)
3. **Claim normalization** — Lowercases text, resolves entity references, removes hedging language
4. **Check-worthiness scoring** — Two-pass LLM scoring protocol producing a 0.0–1.0 score
5. **Entity extraction** — LLM-powered NER for persons, organizations, dates, locations, and statistics

## Tools

| Tool | Description |
|------|-------------|
| `validate_claim_text()` | Structural validation of claim text |
| `validate_source_url()` | URL format and accessibility check |
| `normalize_date()` | Date normalization to YYYYMMDD |
| `check_duplicate()` | Deduplication against existing claims |
| `build_prompt()` | Constructs domain classification prompt |
| `call_claude()` | LLM invocation for classification (2 attempts) |
| `normalize_claim_text()` | Text normalization pipeline |
| `score_claim_text()` | Two-pass check-worthiness scoring |
| `extract_entities_llm()` | LLM-powered named entity extraction |

## Input

| Field | Type | Description |
|-------|------|-------------|
| `claim_text` | `str` | Raw claim text as submitted |
| `claim_url` | `str \| None` | Source article URL |
| `submission_date` | `str \| None` | Date of submission |

Typed model: `IntakeInput` in `agents/intake/models.py`

## Output

| Field | Type | Description |
|-------|------|-------------|
| `normalized_claim` | `str` | Normalized claim text |
| `claim_domain` | `str` | Domain classification |
| `check_worthy_score` | `float` | Check-worthiness score (0.0–1.0) |
| `is_check_worthy` | `bool` | Gate result (score ≥ 0.4) |
| `entities` | `dict` | Extracted entities by type |

Typed model: `IntakeOutput` in `agents/intake/models.py`

## Observation Codes

| Code | Value Type | Owner | Description |
|------|-----------|-------|-------------|
| `CLAIM_TEXT` | ST | ingestion-agent | Raw claim text |
| `CLAIM_SOURCE_URL` | ST | ingestion-agent | Source article URL |
| `CLAIM_SOURCE_DATE` | ST | ingestion-agent | Publication date (YYYYMMDD) |
| `CLAIM_DOMAIN` | ST | ingestion-agent | Domain classification |
| `CLAIM_NORMALIZED` | ST | claim-detector | Normalized claim text |
| `CHECK_WORTHY_SCORE` | NM | claim-detector | Check-worthiness score (0.0–1.0) |
| `ENTITY_PERSON` | ST | entity-extractor | Named person (one per entity) |
| `ENTITY_ORG` | ST | entity-extractor | Named organization |
| `ENTITY_DATE` | ST | entity-extractor | Temporal reference |
| `ENTITY_LOCATION` | ST | entity-extractor | Geographic location |
| `ENTITY_STATISTIC` | ST | entity-extractor | Numeric claim / quantity |

## External Dependencies

None. All processing is local or LLM-based.

## Invariants

- **INV-1**: Check-worthiness scoring uses a two-pass protocol — preliminary (P) then final (F) status.
- **INV-2**: If `check_worthy_score < 0.4`, entity extraction is skipped and the pipeline routes directly to the synthesizer bypass.
- **INV-3**: Domain classification retries once on LLM error before falling back to `OTHER`.
- **INV-4**: Each entity type produces one observation per extracted entity (not a single list observation).

## Routing Behavior

After intake completes, the pipeline router checks `is_check_worthy`:
- **True** → parallel fan-out to Evidence and Coverage nodes
- **False** → direct bypass to Synthesizer (verdict = `NOT_CHECK_WORTHY`, confidence = 1.0)
