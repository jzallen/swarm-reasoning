## Context

Phases 1 and 2 deliver the foundational data layer, orchestrator, and all Phase 2 fan-out agents (ingestion, claim-detector, entity-extractor, claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence, source-validator). This slice implements the blindspot-detector: the first Phase 3 agent that operates after the fan-out completes.

Key constraints from architecture:
- **ADR-0016**: Temporal.io orchestration -- the blindspot-detector runs as a Temporal activity worker. The orchestrator Temporal workflow reads COVERAGE_* observations from the three coverage agents' streams and SOURCE_CONVERGENCE_SCORE from the source-validator's stream, then passes them as activity input. No MCP servers, no direct stream reads by the agent.
- **ADR-0003**: Append-only log -- the agent never modifies existing observations; it reads F-status COVERAGE_* observations (via activity input) and publishes new BLINDSPOT_* observations.
- **ADR-0004**: Tool-based observation construction -- the LLM never writes raw JSON observations; the tool layer enforces schema validity at write time.
- **ADR-0012**: ReasoningStream interface -- agent is transport-agnostic; uses the abstract interface backed by Redis in dev.
- **ADR-0013**: Two communication planes -- Temporal control plane + Redis Streams data plane.
- **ADR-0021**: Source-validator agent -- provides SOURCE_CONVERGENCE_SCORE as additional input to the blindspot-detector.

The agent owns exactly three OBX codes (from `docs/domain/obx-code-registry.json`):
- `BLINDSPOT_SCORE` (NM, 0.0-1.0): degree of coverage asymmetry
- `BLINDSPOT_DIRECTION` (CWE: LEFT/RIGHT/CENTER/MULTIPLE/NONE): which segment is absent or underrepresented
- `CROSS_SPECTRUM_CORROBORATION` (CWE: TRUE/FALSE): whether all three segments cover the claim consistently

The input signals it reads via Temporal activity input are:
- `COVERAGE_ARTICLE_COUNT` (NM) -- one per coverage agent
- `COVERAGE_FRAMING` (CWE: SUPPORTIVE/CRITICAL/NEUTRAL/ABSENT) -- one per coverage agent
- `SOURCE_CONVERGENCE_SCORE` (NM, 0.0-1.0) -- from source-validator (optional; strengthens analysis)

## Goals / Non-Goals

**Goals:**
- Implement Temporal activity worker that receives cross-agent coverage data as activity input
- Compute BLINDSPOT_SCORE and BLINDSPOT_DIRECTION from article counts and framing across the three spectrum segments
- Compute CROSS_SPECTRUM_CORROBORATION from presence and consistency of coverage across all three segments
- Incorporate SOURCE_CONVERGENCE_SCORE as a corroboration strengthener (high convergence + all-present coverage = stronger corroboration signal)
- Publish exactly three F-status observations per successful run; emit STOP finalStatus=F on success, STOP finalStatus=X on data corruption
- Publish progress events to `progress:{runId}` for SSE relay
- Write unit tests for asymmetry scoring, direction classification, and corroboration logic
- Write integration tests for the activity flow and stream output

**Non-Goals:**
- Fetching or parsing raw news articles (that is coverage agents' responsibility)
- Producing a verdict or confidence score (synthesizer's responsibility)
- Defining new OBX codes beyond the three owned by this agent
- Implementing any TypeScript layer (Python only)
- Reading Redis Streams directly (receives data as Temporal activity input from the orchestrator)

## Decisions

### 1. Cross-agent data via Temporal activity input

The orchestrator Temporal workflow reads coverage data from the three coverage agents' streams and SOURCE_CONVERGENCE_SCORE from the source-validator's stream, then passes them as the `cross_agent_data` field of `FanoutActivityInput`. This replaces the MCP pull pattern from the previous design and is consistent with ADR-0016.

The `cross_agent_data` dict contains:
```python
{
    "coverage": {
        "left": {"article_count": 12, "framing": "SUPPORTIVE"},
        "center": {"article_count": 7, "framing": "NEUTRAL"},
        "right": {"article_count": 0, "framing": "ABSENT"}
    },
    "source_convergence_score": 0.35  # from source-validator, optional
}
```

**Alternative considered:** Have the agent read Redis Streams directly. Rejected -- the orchestrator workflow mediates all cross-agent data access (consistent with ADR-0016 and the source-validator pattern).

### 2. BLINDSPOT_SCORE formula

```
absent_count = number of segments where COVERAGE_FRAMING == ABSENT or COVERAGE_ARTICLE_COUNT == 0
score = absent_count / 3
```

- 0 absent segments -> score 0.0 (no blindspot)
- 1 absent segment -> score 0.33
- 2 absent segments -> score 0.67
- 3 absent segments -> score 1.0 (complete blindspot)

Simple and interpretable. The synthesizer treats scores above 0.5 as a significant coverage gap signal.

**Alternative considered:** Weighted Gini coefficient across article counts. Rejected -- more complex, harder to explain in the verdict narrative, and the article count magnitudes are not normalized across sources.

### 3. BLINDSPOT_DIRECTION classification

If `absent_count == 0`, direction is `NONE^No Blindspot^FCK`.
If `absent_count == 1`, direction identifies the absent segment: `LEFT^Left Absent^FCK`, `RIGHT^Right Absent^FCK`, or `CENTER^Center Absent^FCK`.
If `absent_count >= 2`, direction is `MULTIPLE^Multiple Absent^FCK` (multiple segments are missing; specific segments are implicit from the score).

**Rationale:** Using MULTIPLE instead of trying to pick a "primary" absent segment avoids ambiguity when 2+ segments are missing. The synthesizer reads BLINDSPOT_SCORE for severity.

### 4. CROSS_SPECTRUM_CORROBORATION logic

`TRUE^Corroborated^FCK` requires all three conditions:
1. All three segments have `COVERAGE_FRAMING != ABSENT`
2. All three segments have `COVERAGE_ARTICLE_COUNT > 0`
3. No two segments have directly opposing framing (SUPPORTIVE vs CRITICAL)

If any condition fails: `FALSE^Not Corroborated^FCK`.

**Enhancement from SOURCE_CONVERGENCE_SCORE:** When SOURCE_CONVERGENCE_SCORE > 0.5 and all three conditions above are met, the corroboration is considered "strong" -- this is noted in the observation's `note` field but does not change the coded value. The synthesizer uses the convergence score independently in its confidence model.

**Rationale:** Corroboration requires presence AND consistency. A claim covered by all three segments but with SUPPORTIVE framing on the left and CRITICAL on the right is not corroborated -- it is contested.

### 5. Graceful degradation on missing coverage data

If the orchestrator passes an empty coverage dict (e.g., coverage agents timed out), the agent:
- Publishes `BLINDSPOT_SCORE = 1.0` (worst case -- no data is the worst blindspot)
- Publishes `BLINDSPOT_DIRECTION = NONE^No Blindspot^FCK` (direction is indeterminate with no data)
- Publishes `CROSS_SPECTRUM_CORROBORATION = FALSE^Not Corroborated^FCK`
- Closes with `STOP finalStatus=F` (not X) -- the absence of data is itself a valid finding

**Alternative considered:** `STOP finalStatus=X` on empty data. Rejected -- an empty observation set is a real signal that the synthesizer should reason about, not a failure to cancel.

### 6. Package structure

```
src/
  swarm_reasoning/
    agents/
      blindspot_detector/
        __init__.py
        activity.py        -- BlindspotDetectorActivity(FanoutActivity): Temporal activity, lifecycle
        analysis.py        -- Asymmetry scoring, direction classification, corroboration logic
        models.py          -- SegmentCoverage, CoverageSnapshot dataclasses
tests/
  unit/
    agents/
      test_blindspot_analysis.py  -- Score formula, direction, corroboration edge cases
  integration/
    agents/
      test_blindspot_flow.py      -- Full activity + stream publish flow
```

## Risks / Trade-offs

- **[Single agent in Phase 3]** -> Phase 3 has the blindspot-detector then the synthesizer (sequential). If blindspot-detector fails (STOP finalStatus=X), the synthesizer must proceed with degraded data. The synthesizer tolerates missing BLINDSPOT_* observations.
- **[Temporal activity input size]** -> The cross-agent data is small (6 coverage observations + 1 convergence score), so activity input size is not a concern.
- **[Corroboration definition is opinionated]** -> Opposing framing (SUPPORTIVE vs CRITICAL) means "not corroborated" even if all segments cover the claim. This is an intentional design choice -- coverage without agreement is not corroboration.
- **[SOURCE_CONVERGENCE_SCORE is optional]** -> If the source-validator timed out or published X-status, the convergence score may be absent. The blindspot-detector treats absent convergence as 0.0 (no convergence data).
