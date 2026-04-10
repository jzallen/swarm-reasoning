# Spec: verdict-mapping

## Purpose

Map CONFIDENCE_SCORE to one of seven verdict codes using fixed threshold ranges from docs/domain/entities/verdict.md. Apply ClaimReview override logic when a high-confidence external fact-check exists. Publish VERDICT and SYNTHESIS_OVERRIDE_REASON as F-status OBX observations.

## Inputs

- `confidence_score`: float in [0.0, 1.0], or `None` (from confidence-scoring)
- `resolved_observations`: canonical observation set (from observation-resolution), used to look up CLAIMREVIEW_MATCH, CLAIMREVIEW_VERDICT, CLAIMREVIEW_MATCH_SCORE, CLAIMREVIEW_SOURCE

## Outputs

- `verdict`: string -- one of the seven verdict codes
- VERDICT OBX (F-status)
- SYNTHESIS_OVERRIDE_REASON OBX (F-status) -- always emitted; empty string value when no override occurred

## Verdict Threshold Mapping

Per docs/domain/entities/verdict.md, when `confidence_score` is not None:

| Range                 | Verdict      | CWE Value                           |
|-----------------------|--------------|-------------------------------------|
| 0.90 <= score <= 1.00 | TRUE         | `TRUE^True^POLITIFACT`                     |
| 0.70 <= score < 0.90  | MOSTLY_TRUE  | `MOSTLY_TRUE^Mostly True^POLITIFACT`       |
| 0.45 <= score < 0.70  | HALF_TRUE    | `HALF_TRUE^Half True^POLITIFACT`           |
| 0.25 <= score < 0.45  | MOSTLY_FALSE | `MOSTLY_FALSE^Mostly False^POLITIFACT`     |
| 0.10 <= score < 0.25  | FALSE        | `FALSE^False^POLITIFACT`                   |
| 0.00 <= score < 0.10  | PANTS_FIRE   | `PANTS_FIRE^Pants on Fire^POLITIFACT`      |

When `confidence_score` is None (insufficient evidence):

| Condition            | Verdict      | CWE Value                           |
|----------------------|--------------|-------------------------------------|
| score is None        | UNVERIFIABLE | `UNVERIFIABLE^Unverifiable^FCK`     |

## ClaimReview Override

Evaluate override eligibility after computing the swarm verdict from threshold mapping:

**Override fires when ALL of the following are true:**
1. Resolved CLAIMREVIEW_MATCH = `TRUE^Match Found^FCK`
2. Resolved CLAIMREVIEW_MATCH_SCORE >= 0.90
3. Resolved CLAIMREVIEW_VERDICT differs from the swarm-computed verdict code
4. `confidence_score` is not None (UNVERIFIABLE verdicts are not overridden)

**When override fires:**
- Set `verdict` to the normalized ClaimReview verdict code (mapped from CLAIMREVIEW_VERDICT value to POLITIFACT vocabulary if needed)
- Set `override_reason` to a structured string:
  `"ClaimReview override: {CLAIMREVIEW_SOURCE} rated this claim {CLAIMREVIEW_VERDICT} (match_score={CLAIMREVIEW_MATCH_SCORE:.2f}); swarm computed {swarm_verdict} at confidence {confidence_score:.2f}"`

**When override does not fire:**
- Set `override_reason` to `""` (empty string)
- Verdict remains as threshold-mapped value

**Override does not fire when:**
- CLAIMREVIEW_MATCH is FALSE or absent
- CLAIMREVIEW_MATCH_SCORE < 0.90
- CLAIMREVIEW_VERDICT equals the swarm verdict (agreement -- no override needed)

## OBX Emissions

**VERDICT OBX (seq 3):**
```json
{
  "type": "OBS",
  "observation": {
    "runId": "{runId}",
    "agent": "synthesizer",
    "seq": 3,
    "code": "VERDICT",
    "value": "{verdict_cwe_value}",
    "valueType": "CWE",
    "units": null,
    "referenceRange": null,
    "status": "F",
    "timestamp": "{ISO8601}",
    "method": "map_verdict",
    "note": null
  }
}
```

**SYNTHESIS_OVERRIDE_REASON OBX (seq 5):**
```json
{
  "type": "OBS",
  "observation": {
    "runId": "{runId}",
    "agent": "synthesizer",
    "seq": 5,
    "code": "SYNTHESIS_OVERRIDE_REASON",
    "value": "{override_reason}",
    "valueType": "ST",
    "units": null,
    "referenceRange": null,
    "status": "F",
    "timestamp": "{ISO8601}",
    "method": "map_verdict",
    "note": null
  }
}
```

Note: SYNTHESIS_OVERRIDE_REASON is always emitted. When there is no override, `value` is `""`.

## Acceptance Criteria

- CONFIDENCE_SCORE=0.95 -> VERDICT=TRUE. (verdict-synthesis.feature)
- CONFIDENCE_SCORE=0.75 -> VERDICT=MOSTLY_TRUE. (verdict-synthesis.feature)
- CONFIDENCE_SCORE=0.55 -> VERDICT=HALF_TRUE. (verdict-synthesis.feature)
- CONFIDENCE_SCORE=0.35 -> VERDICT=MOSTLY_FALSE. (verdict-synthesis.feature)
- CONFIDENCE_SCORE=0.18 -> VERDICT=FALSE. (verdict-synthesis.feature)
- CONFIDENCE_SCORE=0.04 -> VERDICT=PANTS_FIRE. (verdict-synthesis.feature)
- Boundary: 0.90 -> TRUE, 0.8999 -> MOSTLY_TRUE (per verdict.md threshold of 0.90)
- Boundary: 0.70 -> MOSTLY_TRUE, 0.6999 -> HALF_TRUE
- Boundary: 0.45 -> HALF_TRUE, 0.4499 -> MOSTLY_FALSE
- Boundary: 0.25 -> MOSTLY_FALSE, 0.2499 -> FALSE
- Boundary: 0.10 -> FALSE, 0.0999 -> PANTS_FIRE
- SYNTHESIS_SIGNAL_COUNT < 5 -> VERDICT=UNVERIFIABLE, CONFIDENCE_SCORE OBX absent.
- CLAIMREVIEW_VERDICT=FALSE and swarm VERDICT=FALSE: SYNTHESIS_OVERRIDE_REASON is empty string.
- CLAIMREVIEW_VERDICT=TRUE, DOMAIN_EVIDENCE_ALIGNMENT=CONTRADICTS, swarm VERDICT=MOSTLY_FALSE, CLAIMREVIEW_MATCH_SCORE >= 0.90: SYNTHESIS_OVERRIDE_REASON is non-empty and references domain evidence.
- Consumer API rejects VERDICT values not in the controlled vocabulary.
