# Spec: verdict-narrative

## Purpose

Generate a human-readable explanation of the verdict that cites specific upstream observations by OBX sequence number and annotates source URLs from the source-validator's CITATION_LIST. Published as a single F-status VERDICT_NARRATIVE OBX. This is the only synthesizer output produced via LLM call.

## Inputs

- `resolved_observations`: canonical observation set with `(code, value, seq, agent)` tuples (from observation-resolution)
- `verdict`: final verdict code string (from verdict-mapping)
- `confidence_score`: float or None (from confidence-scoring)
- `override_reason`: string or `""` (from verdict-mapping)
- `warnings`: list of warning strings from observation-resolution (for P-status signal gaps)
- `synthesis_signal_count`: integer (from observation-resolution)
- `citation_list`: list of Citation objects from resolved CITATION_LIST observation (from source-validator via observation-resolution)

## Outputs

- VERDICT_NARRATIVE OBX (F-status), value length 200-1000 characters

## Narrative Generation

### LLM Prompt Structure

The synthesizer tool constructs a structured prompt with:

**System role:**
> You are a fact-checking verdict narrator. Your job is to explain a fact-checking verdict in plain, accurate language. Cite specific findings using [OBX-{seq}] notation. Reference source URLs with their validation status. Do not hedge unless the verdict is UNVERIFIABLE.

**User message -- structured sections:**

1. **Verdict**: `{verdict}` (confidence: `{confidence_score:.2f}` or "insufficient evidence")
2. **Key findings** -- a formatted list of resolved observations, each on one line:
   ```
   [OBX-{seq}] {agent} / {code}: {value}
   ```
   Include all resolved observations, sorted by seq ascending.
3. **Source citations** -- from CITATION_LIST:
   ```
   - {sourceName} ({validationStatus}): {sourceUrl} [cited by {agent}]
   ```
   Include all citations, noting dead links and soft-404s prominently.
4. **Override** (if present): `ClaimReview override was applied: {override_reason}`
5. **Warnings** (if any): `Coverage gaps: {warnings}`
6. **Instructions**:
   - Write 200-1000 characters
   - Cite at least 3 observations by [OBX-N] notation
   - Reference key source URLs with validation status (e.g., "according to CDC (live source)" or "Reuters article (dead link)")
   - Use plain language appropriate for a news reader
   - For UNVERIFIABLE: explain which signals were missing rather than stating a truth value
   - For PANTS_FIRE: explicitly state the claim is false and cite contradicting evidence
   - Do not include any metadata or JSON

### Fallback Narrative (LLM Failure)

If the LLM call fails or times out (5 s hard timeout), emit a template-generated narrative:

```
Verdict: {verdict}. This determination is based on {synthesis_signal_count} signals from upstream agents. {domain_alignment_sentence} {claimreview_sentence} {corroboration_sentence} {convergence_sentence}{source_sentence}{gap_sentence}
```

Where:
- `domain_alignment_sentence`: "Domain evidence {DOMAIN_EVIDENCE_ALIGNMENT}s the claim." (or "Domain evidence was absent.")
- `claimreview_sentence`: "An external fact-check rated this claim {CLAIMREVIEW_VERDICT}." (or empty if no match)
- `corroboration_sentence`: "Cross-spectrum corroboration was {TRUE/absent}."
- `convergence_sentence`: "Source convergence score: {SOURCE_CONVERGENCE_SCORE:.2f}." (or empty if absent)
- `source_sentence`: " Sources: {citation_count} citations, {live_count} live, {dead_count} dead." (from CITATION_LIST)
- `gap_sentence`: " Note: some upstream signals were incomplete." (if warnings exist)

The fallback narrative must still be 200-1000 characters. If the template produces < 200 characters, pad with a factual statement about the signal count and source quality.

### Length Validation

Before publishing, the synthesizer tool validates:
- `len(narrative) >= 200` -- if not, retry LLM call once with explicit length instruction; if still short, use fallback
- `len(narrative) <= 1000` -- if not, truncate at the last complete sentence before character 1000

## VERDICT_NARRATIVE OBX (seq 4)

```json
{
  "type": "OBS",
  "observation": {
    "runId": "{runId}",
    "agent": "synthesizer",
    "seq": 4,
    "code": "VERDICT_NARRATIVE",
    "value": "{narrative_text}",
    "valueType": "TX",
    "units": null,
    "referenceRange": null,
    "status": "F",
    "timestamp": "{ISO8601}",
    "method": "generate_narrative",
    "note": null
  }
}
```

## OBX Emission Order

The five synthesizer OBX observations are emitted in this sequence:

| seq | code                    | capability            |
|-----|-------------------------|-----------------------|
| 1   | SYNTHESIS_SIGNAL_COUNT  | observation-resolution |
| 2   | CONFIDENCE_SCORE        | confidence-scoring     |
| 3   | VERDICT                 | verdict-mapping        |
| 4   | VERDICT_NARRATIVE       | verdict-narrative      |
| 5   | SYNTHESIS_OVERRIDE_REASON | verdict-mapping      |

CONFIDENCE_SCORE (seq 2) is absent when VERDICT is UNVERIFIABLE.

## STOP Message

After all OBX observations are published, the synthesizer publishes:

```json
{
  "type": "STOP",
  "runId": "{runId}",
  "agent": "synthesizer",
  "finalStatus": "F",
  "observationCount": 5,
  "timestamp": "{ISO8601}"
}
```

`observationCount` is 4 when VERDICT is UNVERIFIABLE (CONFIDENCE_SCORE OBX omitted).

## Acceptance Criteria

- VERDICT_NARRATIVE length is between 200 and 1000 characters.
- VERDICT_NARRATIVE references source URLs from CITATION_LIST with validation status annotations.
- Given BLINDSPOT_SCORE=0.90: VERDICT_NARRATIVE references the blindspot as a confidence-reducing factor.
- Given P-status COVERAGE_FRAMING: VERDICT_NARRATIVE notes incomplete coverage data.
- Given SYNTHESIS_SIGNAL_COUNT < 5: VERDICT_NARRATIVE explains insufficient evidence.
- Given ClaimReview override: SYNTHESIS_OVERRIDE_REASON references the domain evidence finding.
- Synthesizer stream contains F-status VERDICT_NARRATIVE observation with agent="synthesizer".
- STOP message finalStatus="F" and observationCount matches published count.
- Run transitions to completed after synthesizer activity completes.
- Fallback narrative includes source citation summary from CITATION_LIST.
- Dead link sources from CITATION_LIST are noted in the narrative (LLM or fallback).
- Temporal activity returns FanoutActivityResult with status="COMPLETED" on success.
