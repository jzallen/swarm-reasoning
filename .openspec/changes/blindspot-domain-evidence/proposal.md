## Why

Phase 2 produces raw coverage observations from three political spectrum segments (left, center, right) and a source convergence score from the source-validator. Those observations are siloed -- no component yet examines whether coverage is consistent or asymmetric across the spectrum. Without blindspot detection, the synthesizer receives coverage data but cannot characterize gaps: a claim covered only by right-leaning outlets, or corroborated across all three segments, carries very different evidential weight that the synthesizer must account for.

The blindspot-detector is Phase 3 of the execution DAG -- it runs after all Phase 2 agents complete and before the synthesizer. It receives cross-agent data as Temporal activity input from the orchestrator workflow. Its three observation codes (BLINDSPOT_SCORE, BLINDSPOT_DIRECTION, CROSS_SPECTRUM_CORROBORATION) give the synthesizer a quantified signal about coverage asymmetry that it cannot compute itself without coupling to coverage agent internals.

## What Changes

- Implement the `blindspot-detector` as a Temporal activity worker in the shared agent-service container (ADR-0016)
- The orchestrator Temporal workflow reads COVERAGE_* observations from all three coverage agents' streams and SOURCE_CONVERGENCE_SCORE from the source-validator's stream, then passes them as Temporal activity input
- Implement coverage asymmetry analysis: compare COVERAGE_ARTICLE_COUNT and COVERAGE_FRAMING across left/center/right segments, compute BLINDSPOT_SCORE (0.0-1.0) and BLINDSPOT_DIRECTION (CWE coded)
- Incorporate SOURCE_CONVERGENCE_SCORE as additional input to strengthen the analysis
- Implement cross-spectrum corroboration logic: all three segments must have non-ABSENT framing and article count > 0 for CROSS_SPECTRUM_CORROBORATION = TRUE
- Publish three observations per run: BLINDSPOT_SCORE (NM), BLINDSPOT_DIRECTION (CWE), CROSS_SPECTRUM_CORROBORATION (CWE), each with status F
- Publish progress events to `progress:{runId}` for SSE relay
- Stream lifecycle: opens with START, publishes three F-status observations via the tool layer, closes with STOP finalStatus=F; closes with STOP finalStatus=X if coverage data is corrupt

## Capabilities

### New Capabilities

- `blindspot-detection`: Coverage asymmetry analysis using Temporal activity input containing COVERAGE_* observations from all three coverage agents and SOURCE_CONVERGENCE_SCORE from source-validator, then emit BLINDSPOT_SCORE, BLINDSPOT_DIRECTION, and CROSS_SPECTRUM_CORROBORATION observations

### Modified Capabilities

None -- this is a new agent with no prior implementation.

## Impact

- **New package**: `src/swarm_reasoning/agents/blindspot_detector/` (Python)
- **No new containers**: Agent runs as a Temporal activity worker in the shared agent-service container (ADR-0016)
- **Stream output**: produces exactly three F-status observations per run using the ReasoningStream interface
- **Depends on**: Coverage agents (must have published STOP before blindspot-detector is dispatched); source-validator (SOURCE_CONVERGENCE_SCORE as optional input)
- **Downstream unblocked**: synthesizer depends on BLINDSPOT_SCORE and CROSS_SPECTRUM_CORROBORATION as weighted inputs to the final confidence score
- **DAG position**: Phase 3 -- sequential after Phase 2 fan-out, before the synthesizer
