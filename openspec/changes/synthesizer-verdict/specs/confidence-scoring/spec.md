# Spec: confidence-scoring

## Purpose

Compute a calibrated CONFIDENCE_SCORE in [0.0, 1.0] from the resolved upstream observation set using a deterministic weighted signal model incorporating SOURCE_CONVERGENCE_SCORE as a confidence amplifier. The score drives verdict mapping and is published as an F-status OBX.

## Inputs

- `resolved_observations`: canonical observation set produced by `observation-resolution`
- `synthesis_signal_count`: integer from `observation-resolution`

## Outputs

- `confidence_score`: float in [0.0, 1.0], or `None` when UNVERIFIABLE
- CONFIDENCE_SCORE OBX (F-status), or absent when UNVERIFIABLE

## Signal Model

### Early Exit: Insufficient Evidence

If `synthesis_signal_count < 5`, set `confidence_score = None`. Do not emit CONFIDENCE_SCORE OBX. VERDICT will be UNVERIFIABLE (handled by verdict-mapping). VERDICT_NARRATIVE must explain insufficient evidence.

### Signal Lookup

Extract the following resolved observation values (all optional; if absent, treat as contributing 0.0 to weighted sum with full weight deducted):

| Signal Code                  | Owner Agent(s)                              | Role in Score |
|------------------------------|---------------------------------------------|---------------|
| `DOMAIN_EVIDENCE_ALIGNMENT`  | domain-evidence                             | Primary truth signal |
| `DOMAIN_CONFIDENCE`          | domain-evidence                             | Confidence penalty on domain signal |
| `CLAIMREVIEW_MATCH`          | claimreview-matcher                         | External fact-check presence |
| `CLAIMREVIEW_VERDICT`        | claimreview-matcher                         | External fact-check verdict direction |
| `CLAIMREVIEW_MATCH_SCORE`    | claimreview-matcher                         | Trust weight for ClaimReview signal |
| `CROSS_SPECTRUM_CORROBORATION` | blindspot-detector                        | Multi-source corroboration |
| `COVERAGE_FRAMING` (x3)      | coverage-left, coverage-center, coverage-right | Framing consensus |
| `BLINDSPOT_SCORE`            | blindspot-detector                          | Coverage asymmetry penalty |
| `SOURCE_CONVERGENCE_SCORE`   | source-validator                            | Source convergence across agents |

### Component Computation

**Component A -- Domain Evidence (weight 0.30)**

Map `DOMAIN_EVIDENCE_ALIGNMENT` to a raw score:
- `SUPPORTS`: 1.0
- `PARTIAL`: 0.5
- `ABSENT`: 0.25
- `CONTRADICTS`: 0.0

Multiply by `DOMAIN_CONFIDENCE` (default 1.0 if absent). If DOMAIN_EVIDENCE_ALIGNMENT is absent entirely, component A = 0.0 and deduct 0.30 from the effective weight total.

`component_A = domain_alignment_score * domain_confidence * 0.30`

**Component B -- ClaimReview (weight 0.25)**

Only active when CLAIMREVIEW_MATCH is TRUE. When active, use CLAIMREVIEW_MATCH_SCORE as trust weight.

Map CLAIMREVIEW_VERDICT to a truthfulness score using the six-tier confidence midpoints:
- `TRUE`: 0.950
- `MOSTLY_TRUE`: 0.795
- `HALF_TRUE`: 0.570
- `MOSTLY_FALSE`: 0.345
- `FALSE`: 0.170
- `PANTS_FIRE`: 0.045

`component_B = claimreview_truthfulness * match_score * 0.25`

When CLAIMREVIEW_MATCH is FALSE or absent: `component_B = 0.0`, deduct 0.25 from effective weight total.

**Component C -- Cross-Spectrum Corroboration (weight 0.15)**

Map CROSS_SPECTRUM_CORROBORATION:
- `TRUE`: 1.0
- `FALSE`: 0.0
- Absent: 0.0, deduct 0.15 from effective weight total

`component_C = corroboration_score * 0.15`

**Component D -- Coverage Framing Consensus (weight 0.15)**

Average the framing scores from all three coverage agents. Map COVERAGE_FRAMING per agent:
- `SUPPORTIVE`: 1.0
- `NEUTRAL`: 0.5
- `ABSENT`: 0.25
- `CRITICAL`: 0.0

Average available framing scores (1-3 agents). If no coverage framing observations exist, component D = 0.0, deduct 0.15 from effective weight total.

`component_D = avg_framing_score * 0.15`

**Component E -- Source Convergence (weight 0.10)**

Per ADR-0021: "source convergence across agents is a strong signal for confidence scoring."

Use `SOURCE_CONVERGENCE_SCORE` directly (NM value in [0.0, 1.0]). If absent, component E = 0.0, deduct 0.10 from effective weight total.

`component_E = source_convergence_score * 0.10`

**Normalization**

Sum components and divide by the effective weight total (sum of weights for signals that were present):

`raw_score = (component_A + component_B + component_C + component_D + component_E) / effective_weight_total`

Clamp result to [0.0, 1.0].

**Blindspot Penalty**

Apply after normalization:

`confidence_score = raw_score - (BLINDSPOT_SCORE * 0.10)`

Clamp to [0.0, 1.0]. If BLINDSPOT_SCORE is absent, no penalty is applied.

### CONFIDENCE_SCORE OBX

```json
{
  "type": "OBS",
  "observation": {
    "runId": "{runId}",
    "agent": "synthesizer",
    "seq": 2,
    "code": "CONFIDENCE_SCORE",
    "value": "{confidence_score}",
    "valueType": "NM",
    "units": "score",
    "referenceRange": "0.0-1.0",
    "status": "F",
    "timestamp": "{ISO8601}",
    "method": "compute_confidence",
    "note": null
  }
}
```

## Acceptance Criteria

- Given resolved inputs with CLAIMREVIEW_MATCH=TRUE, CLAIMREVIEW_VERDICT=FALSE, DOMAIN_EVIDENCE_ALIGNMENT=CONTRADICTS, CROSS_SPECTRUM_CORROBORATION=TRUE, BLINDSPOT_SCORE=0.12, SOURCE_CONVERGENCE_SCORE=0.5: CONFIDENCE_SCORE is in [0.20, 0.50]. (verdict-synthesis.feature)
- Given CLAIMREVIEW_MATCH=FALSE vs. TRUE under otherwise identical conditions: score with FALSE is lower. (verdict-synthesis.feature)
- Given BLINDSPOT_SCORE=0.90: confidence_score is reduced by 0.09 relative to pre-penalty score. (verdict-synthesis.feature)
- Given SYNTHESIS_SIGNAL_COUNT < 5: CONFIDENCE_SCORE OBX is not emitted. (verdict-synthesis.feature)
- Given SOURCE_CONVERGENCE_SCORE=1.0 vs. 0.0 under otherwise identical conditions: score with 1.0 is higher. (ADR-0021 validation)
- Given SOURCE_CONVERGENCE_SCORE absent: weight 0.10 is deducted from effective weight total; other components are normalized accordingly.
- Swarm verdict accuracy >= 70% on 50-claim PolitiFact corpus. (NFR-019)

## NFR References

- NFR-019: Swarm Verdict Accuracy on PolitiFact Corpus -- >= 70% correct alignment

## ADR References

- ADR-004: Tool-based observation construction -- scoring algorithm is implemented in a tool, not generated by an LLM
- ADR-021: Source-Validator Agent -- SOURCE_CONVERGENCE_SCORE as confidence signal
