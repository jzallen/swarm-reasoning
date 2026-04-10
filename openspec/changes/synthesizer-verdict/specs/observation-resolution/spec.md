# Spec: observation-resolution

## Purpose

Read all upstream agent observation streams for a given `runId`, apply epistemic status precedence rules, and produce a canonical resolved observation set that serves as the sole input to confidence scoring and narrative generation.

## Inputs

- `runId`: string -- the run identifier, used to construct stream keys `reasoning:{runId}:{agent}` for all 10 upstream agents
- Redis Streams access via `ReasoningStream` interface (ADR-012)

## Upstream Agent Streams (10 agents)

1. `reasoning:{runId}:ingestion-agent`
2. `reasoning:{runId}:claim-detector`
3. `reasoning:{runId}:entity-extractor`
4. `reasoning:{runId}:claimreview-matcher`
5. `reasoning:{runId}:coverage-left`
6. `reasoning:{runId}:coverage-center`
7. `reasoning:{runId}:coverage-right`
8. `reasoning:{runId}:domain-evidence`
9. `reasoning:{runId}:source-validator`
10. `reasoning:{runId}:blindspot-detector`

## Outputs

- `resolved_observations`: list of canonical observation records, one per (agent, code) pair that has at least one F or C-status observation
- `synthesis_signal_count`: integer -- count of (agent, code) pairs in `resolved_observations`
- `excluded_observations`: list of observation records with status X or P (logged, not used in synthesis)
- `warnings`: list of strings -- populated when P-status observations are encountered (signals incomplete upstream data)

## Resolution Algorithm

For each (agent, code) pair across all upstream streams:

1. Collect all OBX observations for this (agent, code) pair, ordered by `seq` ascending.
2. Filter to C-status observations. If any exist, select the one with the highest `seq`. This is the canonical value. Record `resolution_method = "LATEST_C"`.
3. If no C-status observations exist, filter to F-status observations. If any exist, select the one with the highest `seq`. This is the canonical value. Record `resolution_method = "LATEST_F"`.
4. If only X-status or P-status observations exist, exclude this (agent, code) pair from the resolved set.
   - X-status: add to `excluded_observations`, no warning.
   - P-status: add to `excluded_observations`, add warning string `"WARNING: {agent}:{code} has only P-status observations; upstream agent may not have finalized."`.
5. (agent, code) pairs with no observations of any status are silently absent from the resolved set.

`synthesis_signal_count` = len(`resolved_observations`).

## Stream Reading

Streams are read using `XRANGE reasoning:{runId}:{agent} - +` for each of the 10 upstream agents. The synthesizer's own stream is not read. The orchestrator guarantees all 10 agents have published STOP messages before invoking the synthesizer, so all observations are available.

## SYNTHESIS_SIGNAL_COUNT OBX

After resolution, emit an F-status OBX:

```json
{
  "type": "OBS",
  "observation": {
    "runId": "{runId}",
    "agent": "synthesizer",
    "seq": 1,
    "code": "SYNTHESIS_SIGNAL_COUNT",
    "value": "{synthesis_signal_count}",
    "valueType": "NM",
    "units": "count",
    "referenceRange": null,
    "status": "F",
    "timestamp": "{ISO8601}",
    "method": "resolve_observations",
    "note": null
  }
}
```

## Acceptance Criteria

- Given observation log contains CONFIDENCE_SCORE at seq=14 (F) and seq=31 (C), resolved value is the seq=31 value and resolution_method is "LATEST_C". (verdict-synthesis.feature: "Synthesizer uses latest C-status observation when corrections exist")
- Given observation log contains CLAIMREVIEW_VERDICT at seq=5 (F) only, resolved value is seq=5 value and resolution_method is "LATEST_F". (verdict-synthesis.feature: "Synthesizer uses latest F-status observation when no corrections exist")
- Given DOMAIN_CONFIDENCE at seq=9 (X), it is not included in resolved set and SYNTHESIS_SIGNAL_COUNT does not count it. (verdict-synthesis.feature: "Synthesizer excludes X-status observations from synthesis")
- Given COVERAGE_FRAMING at status P only, it is not included in resolved set and a warning is recorded. (verdict-synthesis.feature: "Synthesizer excludes P-status observations from synthesis")
- SYNTHESIS_SIGNAL_COUNT exactly matches count of resolved (agent, code) pairs for all 50 corpus claims. (NFR-021)
- Source-validator observations (SOURCE_EXTRACTED_URL, SOURCE_VALIDATION_STATUS, SOURCE_CONVERGENCE_SCORE, CITATION_LIST) are included in the resolution when present.

## NFR References

- NFR-021: SYNTHESIS_SIGNAL_COUNT Accurately Reflects Evidence Breadth -- zero discrepancy across all 50 corpus claims

## ADR References

- ADR-003: Append-Only Observation Log -- observations are never overwritten; resolution is a read-time view
- ADR-005: Epistemic Status Carrier -- C > F, X excluded
- ADR-021: Source-Validator Agent -- 4 new observation codes included in resolution
