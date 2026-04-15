## 1. Package Setup

- [x] 1.1 Create Python package structure: `src/swarm_reasoning/agents/blindspot_detector/` with `__init__.py`, `activity.py`, `analysis.py`, `models.py`
- [x] 1.2 Create test directory structure: `tests/unit/agents/test_blindspot_analysis.py`, `tests/integration/agents/test_blindspot_flow.py`
- [x] 1.3 Add dependencies to agent-service requirements: `pydantic>=2.0`, `pytest`, `pytest-asyncio`

## 2. Data Models

- [x] 2.1 Implement `SegmentCoverage` dataclass in `models.py`: `article_count: int`, `framing: str`
- [x] 2.2 Implement `CoverageSnapshot` dataclass in `models.py`: `left: SegmentCoverage`, `center: SegmentCoverage`, `right: SegmentCoverage`, `source_convergence_score: float | None`
- [x] 2.3 Implement `CoverageSnapshot.from_activity_input(data: dict) -> CoverageSnapshot` class method -- parses `cross_agent_data` dict from Temporal activity input, handles missing segments by defaulting to `article_count=0, framing="ABSENT"`, handles missing source_convergence_score by defaulting to None
- [x] 2.4 Write unit tests: `from_activity_input` with full data, partial data (one segment missing), empty dict, data with source_convergence_score, data without source_convergence_score

## 3. Analysis Logic

- [x] 3.1 Implement `compute_blindspot_score(coverage: CoverageSnapshot) -> float` in `analysis.py` -- absent count / 3, rounded to 4 decimal places
- [x] 3.2 Implement `compute_blindspot_direction(coverage: CoverageSnapshot) -> str` in `analysis.py` -- returns CWE coded string: NONE, LEFT, CENTER, RIGHT, or MULTIPLE
- [x] 3.3 Implement `compute_corroboration(coverage: CoverageSnapshot) -> tuple[str, str | None]` in `analysis.py` -- returns (CWE coded string TRUE or FALSE, optional note about convergence strength)
- [x] 3.4 Implement convergence-enhanced corroboration note: when CROSS_SPECTRUM_CORROBORATION = TRUE and source_convergence_score > 0.5, add note "Strong corroboration: source convergence score {score}"
- [x] 3.5 Write unit tests for `compute_blindspot_score`: 0 absent -> 0.0, 1 absent -> 0.3333, 2 absent -> 0.6667, 3 absent -> 1.0
- [x] 3.6 Write unit tests for `compute_blindspot_direction`: no absent -> NONE, single absent left -> LEFT, single absent right -> RIGHT, single absent center -> CENTER, two absent -> MULTIPLE, three absent -> MULTIPLE
- [x] 3.7 Write unit tests for `compute_corroboration`: all present + no conflict -> TRUE, one ABSENT -> FALSE, SUPPORTIVE+CRITICAL conflict -> FALSE, all NEUTRAL -> TRUE, all SUPPORTIVE -> TRUE
- [x] 3.8 Write unit test: corroboration with high convergence score adds note
- [x] 3.9 Write unit test: corroboration with absent convergence score (None) produces no note
- [x] 3.10 Write unit test: article_count = 0 treated same as framing = ABSENT for score and direction

## 4. Blindspot Detector Activity

- [x] 4.1 Create `src/swarm_reasoning/agents/blindspot_detector/activity.py` with `BlindspotDetectorActivity(FanoutActivity)`
- [x] 4.2 Implement `_execute()`: parse CoverageSnapshot from cross_agent_data -> run analysis -> publish three OBX observations -> publish progress events
- [x] 4.3 Implement observation publishing: BLINDSPOT_SCORE (seq 1, NM), BLINDSPOT_DIRECTION (seq 2, CWE), CROSS_SPECTRUM_CORROBORATION (seq 3, CWE), all status = F
- [x] 4.4 Implement graceful degradation: empty coverage data -> score 1.0, direction NONE, corroboration FALSE, STOP finalStatus=F
- [x] 4.5 Implement error handling: malformed cross_agent_data -> log error, publish STOP finalStatus=X
- [x] 4.6 Implement progress event publishing: "Analyzing coverage blindspots...", "Blindspot score: {score}, direction: {direction}", "Cross-spectrum corroboration: {result}"
- [x] 4.7 Write unit test for `_execute`: full data path produces 3 observations + STOP finalStatus=F
- [x] 4.8 Write unit test for `_execute`: empty data path produces degraded observations + STOP finalStatus=F

## 5. Temporal Activity Registration

- [x] 5.1 Register `run_blindspot_detector` Temporal activity in `src/swarm_reasoning/agents/activities.py`: instantiates BlindspotDetectorActivity, calls run(), returns FanoutActivityResult
- [x] 5.2 Configure activity options: start_to_close_timeout=30s (Phase 3 budget), retry_policy with max_attempts=2
- [x] 5.3 Update orchestrator workflow to read COVERAGE_* and SOURCE_CONVERGENCE_SCORE observations from Redis Streams and pass as cross_agent_data when dispatching blindspot-detector
- [x] 5.4 Write unit test: verify run_blindspot_detector activity is importable with correct @activity.defn decorator

## 6. Integration Tests

- [x] 6.1 Write integration test: full activity flow -- mock orchestrator provides coverage data via activity input, verify three F-status observations in stream and STOP finalStatus=F
- [x] 6.2 Write integration test: graceful degradation -- empty coverage input, verify score=1.0 observations and STOP finalStatus=F
- [x] 6.3 Write integration test: BLINDSPOT_SCORE = 0.0 path -- all three segments present and non-conflicting, verify CROSS_SPECTRUM_CORROBORATION = TRUE
- [x] 6.4 Write integration test: conflicting framing -- left=SUPPORTIVE, right=CRITICAL, center=NEUTRAL; verify CROSS_SPECTRUM_CORROBORATION = FALSE
- [x] 6.5 Write integration test: observation ordering -- seq numbers are 1, 2, 3 in ascending order with no gaps
- [x] 6.6 Write integration test: verify progress events published to `progress:{runId}` stream
- [x] 6.7 Write integration test: SOURCE_CONVERGENCE_SCORE = 0.8 with all segments present -> corroboration note includes convergence strength
- [x] 6.8 Write integration test: SOURCE_CONVERGENCE_SCORE absent (None) -> no convergence note, corroboration still computed from coverage data alone

## 7. Gherkin Scenario Validation

- [x] 7.1 Manually verify "Blindspot detector requests data via orchestrator" scenario from `docs/features/agent-coordination.feature` against Temporal activity input pattern (replaces MCP pull)
- [x] 7.2 Manually verify "Each subagent exposes get_observations tool" -- in Temporal model, observations are read from the agent's Redis Stream by the orchestrator, not via an MCP tool
- [x] 7.3 Manually verify "Each subagent exposes get_terminal_status tool" -- in Temporal model, terminal status is determined by the activity result, not via an MCP tool
- [x] 7.4 Confirm phase gate ("Blindspot detector is not dispatched until coverage agents are complete") is enforced by the orchestrator Temporal workflow, not by this agent
- [ ] 7.5 Update Gherkin scenarios if needed to reflect Temporal activity model instead of MCP pull pattern
