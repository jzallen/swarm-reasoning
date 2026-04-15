# Agent: Synthesizer

## Overview

| Field | Value |
|-------|-------|
| **Agent ID** | `synthesizer` |
| **Pipeline Phase** | Phase 4 — Terminal Synthesis |
| **Pipeline Node** | `pipeline/nodes/synthesizer.py` |
| **Agent Module** | `agents/synthesizer/` |
| **Execution Model** | Fixed-order StateGraph (resolve → score → map → narrate) |
| **Consolidates** | `synthesizer` (single agent, unchanged) |

The synthesizer is the terminal pipeline node. It receives the full observation set from all upstream agents, resolves conflicting observations by epistemic status, computes a calibrated confidence score, maps that score to a verdict, and generates a human-readable narrative explaining the verdict with source citations. It also handles the not-check-worthy bypass path.

## Capabilities

1. **Observation resolution** — Resolves observations by epistemic status precedence: F (final) > C (corrected) > P (preliminary). Cancelled (X) observations are excluded.
2. **Confidence scoring** — Multi-component calibrated score incorporating evidence alignment, coverage convergence, blindspot penalty, and domain evidence strength
3. **Verdict mapping** — Maps confidence score to verdict using defined thresholds, with ClaimReview override logic
4. **Narrative generation** — LLM-generated human-readable explanation referencing specific upstream findings

## Tools

| Tool | Module | Description |
|------|--------|-------------|
| `resolve_from_state()` | `synthesizer/resolver.py` | Resolves observations by epistemic status precedence |
| `ConfidenceScorer.compute()` | `synthesizer/scorer.py` | Multi-component confidence scoring |
| `VerdictMapper.map_verdict()` | `synthesizer/mapper.py` | Confidence → verdict with override logic |
| `NarrativeGenerator.generate()` | `synthesizer/narrator.py` | LLM-powered verdict explanation |

## Input

The synthesizer receives the full `PipelineState` containing all upstream outputs:

| Field | Source | Description |
|-------|--------|-------------|
| `normalized_claim` | Intake | Normalized claim text |
| `claim_domain` | Intake | Domain classification |
| `check_worthy_score` | Intake | Check-worthiness score |
| `entities` | Intake | Extracted named entities |
| `claimreview_matches` | Evidence | Existing fact-check matches |
| `domain_sources` | Evidence | Authoritative source findings |
| `evidence_confidence` | Evidence | Evidence confidence score |
| `coverage_left` | Coverage | Left-spectrum analysis |
| `coverage_center` | Coverage | Center-spectrum analysis |
| `coverage_right` | Coverage | Right-spectrum analysis |
| `validated_urls` | Validation | URL validation results |
| `convergence_score` | Validation | Source convergence score |
| `citations` | Validation | Aggregated citation list |
| `blindspot_score` | Validation | Coverage asymmetry score |
| `blindspot_direction` | Validation | Absent spectrum direction |

Typed model: `SynthesizerInput` in `agents/synthesizer/models.py`

## Output

| Field | Type | Description |
|-------|------|-------------|
| `verdict` | `str` | Final verdict (coded value) |
| `confidence` | `float` | Calibrated confidence score (0.0–1.0) |
| `narrative` | `str` | Human-readable verdict explanation (max 1000 chars) |
| `override_reason` | `str \| None` | Reason if ClaimReview verdict was overridden |

Typed model: `SynthesizerOutput` in `agents/synthesizer/models.py`

## Observation Codes

| Code | Value Type | Description |
|------|-----------|-------------|
| `SYNTHESIS_SIGNAL_COUNT` | NM | Number of F-status observations used as input |
| `CONFIDENCE_SCORE` | NM | Final calibrated confidence score (0.0–1.0) |
| `VERDICT` | CWE | Final verdict (see verdict scale below) |
| `SYNTHESIS_OVERRIDE_REASON` | ST | Override explanation (empty if no override) |
| `VERDICT_NARRATIVE` | TX | Human-readable explanation (max 1000 chars) |

## Verdict Scale

Confidence score maps to verdict per observation-schema-spec.md Section 9:

| Confidence Range | Verdict |
|-----------------|---------|
| 0.85–1.00 | TRUE |
| 0.70–0.84 | MOSTLY_TRUE |
| 0.45–0.69 | HALF_TRUE |
| 0.30–0.44 | MOSTLY_FALSE |
| 0.00–0.29 | FALSE |
| < 5 signals | UNVERIFIABLE |
| score < 0.4 (intake) | NOT_CHECK_WORTHY |

## ClaimReview Override Logic

If a high-confidence ClaimReview match exists (match_score ≥ 0.75), the synthesizer may override its computed verdict to align with the existing fact-check. The override is recorded in `SYNTHESIS_OVERRIDE_REASON`.

## External Dependencies

None. All inputs come from upstream pipeline nodes.

## Invariants

- **INV-1**: If `SYNTHESIS_SIGNAL_COUNT < 5`, the verdict is `UNVERIFIABLE` regardless of confidence components.
- **INV-2**: The four internal steps (resolve → score → map → narrate) always execute in this order.
- **INV-3**: The narrative must reference specific upstream findings by observation, not make unsupported claims.
- **INV-4**: The not-check-worthy bypass path produces `VERDICT = NOT_CHECK_WORTHY` with `CONFIDENCE = 1.0` without running the full synthesis.
- **INV-5**: Corrected (C) observations supersede their preliminary (P) counterparts during resolution.

## Bypass Path

When the intake agent scores `check_worthy_score < 0.4`, the pipeline router sends the claim directly to the synthesizer's bypass handler:

- Verdict: `NOT_CHECK_WORTHY`
- Confidence: `1.0`
- Narrative: Generated explanation of why the claim is not check-worthy
- No upstream evidence or coverage is gathered
