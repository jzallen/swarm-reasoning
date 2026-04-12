# Capability: blindspot-detection

Coverage asymmetry analysis using Temporal activity input containing COVERAGE_* observations from all three coverage agents and SOURCE_CONVERGENCE_SCORE from source-validator, then emit BLINDSPOT_SCORE, BLINDSPOT_DIRECTION, and CROSS_SPECTRUM_CORROBORATION observations.

---

## Temporal Activity Interface

The blindspot-detector runs as a Temporal activity worker in the shared agent-service container (ADR-0016). The orchestrator dispatches it in Phase 3 after all Phase 2 agents have published STOP.

### Activity Definition

```python
@activity.defn
async def run_blindspot_detector(input: FanoutActivityInput) -> FanoutActivityResult:
    """Analyze coverage blindspots across the three spectrum segments."""
    agent = BlindspotDetectorActivity(input)
    return await agent.run()
```

**Input:** `FanoutActivityInput` with `cross_agent_data` containing:
```json
{
    "coverage": {
        "left": {"article_count": 12, "framing": "SUPPORTIVE"},
        "center": {"article_count": 7, "framing": "NEUTRAL"},
        "right": {"article_count": 0, "framing": "ABSENT"}
    },
    "source_convergence_score": 0.35
}
```

**Result:** `FanoutActivityResult` with `status` ("COMPLETED" or "CANCELLED"), `observation_count` (3 on success), `error_reason` (if cancelled).

If a segment has no F-status observations from the orchestrator read: `article_count = 0`, `framing = "ABSENT"`.
If source_convergence_score is not available: defaults to `None`.

---

## Analysis Logic

### BLINDSPOT_SCORE

```python
def compute_blindspot_score(coverage: CoverageSnapshot) -> float:
    absent_count = sum(
        1 for seg in [coverage.left, coverage.center, coverage.right]
        if seg.framing == "ABSENT" or seg.article_count == 0
    )
    return round(absent_count / 3, 4)
```

Range: 0.0 (no gap) to 1.0 (all three segments absent). Rounded to 4 decimal places.

### BLINDSPOT_DIRECTION

```python
def compute_blindspot_direction(coverage: CoverageSnapshot) -> str:
    absent_segments = [
        seg_name for seg_name, seg in [("LEFT", coverage.left), ("CENTER", coverage.center), ("RIGHT", coverage.right)]
        if seg.framing == "ABSENT" or seg.article_count == 0
    ]
    if not absent_segments:
        return "NONE^No Blindspot^FCK"
    if len(absent_segments) >= 2:
        return "MULTIPLE^Multiple Absent^FCK"
    return f"{absent_segments[0]}^{absent_segments[0].capitalize()} Absent^FCK"
```

Coded values: `LEFT^Left Absent^FCK`, `RIGHT^Right Absent^FCK`, `CENTER^Center Absent^FCK`, `MULTIPLE^Multiple Absent^FCK`, `NONE^No Blindspot^FCK`.

### CROSS_SPECTRUM_CORROBORATION

```python
def compute_corroboration(coverage: CoverageSnapshot) -> tuple[str, str | None]:
    segments = [coverage.left, coverage.center, coverage.right]
    all_present = all(seg.framing != "ABSENT" and seg.article_count > 0 for seg in segments)
    framings = {seg.framing for seg in segments}
    no_conflict = not ("SUPPORTIVE" in framings and "CRITICAL" in framings)
    if all_present and no_conflict:
        note = None
        if coverage.source_convergence_score is not None and coverage.source_convergence_score > 0.5:
            note = f"Strong corroboration: source convergence score {coverage.source_convergence_score:.2f}"
        return "TRUE^Corroborated^FCK", note
    return "FALSE^Not Corroborated^FCK", None
```

---

## Observation Output

The agent publishes exactly three observations per run (all status F):

| Seq | Code | Value Type | Example Value |
|-----|------|-----------|---------------|
| 1 | BLINDSPOT_SCORE | NM | 0.3333 |
| 2 | BLINDSPOT_DIRECTION | CWE | RIGHT^Right Absent^FCK |
| 3 | CROSS_SPECTRUM_CORROBORATION | CWE | FALSE^Not Corroborated^FCK |

All observations carry:
- `agent`: `"blindspot-detector"`
- `status`: `"F"` (final)
- `runId`: the run being analyzed
- `timestamp`: ISO 8601 UTC

---

## Stream Lifecycle

```
START (msgType=START, agent=blindspot-detector, runId=...)
  OBS seq=1  code=BLINDSPOT_SCORE             status=F  value=0.3333
  OBS seq=2  code=BLINDSPOT_DIRECTION         status=F  value=RIGHT^Right Absent^FCK
  OBS seq=3  code=CROSS_SPECTRUM_CORROBORATION status=F  value=FALSE^Not Corroborated^FCK
STOP  (finalStatus=F, observationCount=3)
```

**On graceful degradation (no coverage data):**
```
START
  OBS seq=1  BLINDSPOT_SCORE             = 1.0
  OBS seq=2  BLINDSPOT_DIRECTION         = NONE^No Blindspot^FCK
  OBS seq=3  CROSS_SPECTRUM_CORROBORATION = FALSE^Not Corroborated^FCK
STOP (finalStatus=F)
```

**On unrecoverable error** (e.g., malformed activity input, schema validation failure):
```
START
STOP (finalStatus=X)
```

---

## Progress Events

The agent publishes progress events to `progress:{runId}` for SSE relay to the frontend (ADR-0018):

1. "Analyzing coverage blindspots..." -- at activity start
2. "Blindspot score: {score:.2f}, direction: {direction}" -- after scoring
3. "Cross-spectrum corroboration: {TRUE/FALSE}" -- after corroboration check

---

## Acceptance Criteria

- [ ] Agent publishes exactly 3 F-status observations per successful run before STOP
- [ ] BLINDSPOT_SCORE is in range [0.0, 1.0]
- [ ] BLINDSPOT_DIRECTION is one of: LEFT^Left Absent^FCK, RIGHT^Right Absent^FCK, CENTER^Center Absent^FCK, MULTIPLE^Multiple Absent^FCK, NONE^No Blindspot^FCK
- [ ] CROSS_SPECTRUM_CORROBORATION is one of: TRUE^Corroborated^FCK, FALSE^Not Corroborated^FCK
- [ ] Score 0.0 is emitted when all three segments have non-ABSENT framing and article_count > 0
- [ ] Score 1.0 is emitted when all three segments return ABSENT/zero
- [ ] Corroboration is FALSE when SUPPORTIVE and CRITICAL framings coexist
- [ ] Empty coverage input produces score 1.0 and STOP finalStatus=F (not X)
- [ ] SOURCE_CONVERGENCE_SCORE > 0.5 with all present segments adds convergence note to corroboration observation
- [ ] SOURCE_CONVERGENCE_SCORE absent (None) produces no convergence note; corroboration computed from coverage data alone
- [ ] No observation is published with status P; all three observations are F at write time
- [ ] CROSS_SPECTRUM_CORROBORATION value type is CWE (not NM) per OBX registry
- [ ] Two absent segments produce BLINDSPOT_DIRECTION = MULTIPLE^Multiple Absent^FCK
- [ ] Temporal activity returns FanoutActivityResult with status="COMPLETED" and observation_count=3 on success
- [ ] Progress events are published to progress:{runId} stream at each analysis step
