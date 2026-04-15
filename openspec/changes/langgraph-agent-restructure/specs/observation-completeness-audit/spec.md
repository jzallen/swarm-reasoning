## ADDED Requirements

### Requirement: Observation manifest maps codes to pipeline nodes
An observation manifest file (`tests/fixtures/observation_manifest.json`) SHALL map each of the 36 OBX codes to its owning pipeline node, expected agent identity, value type, and whether it is mandatory or conditional for a check-worthy claim.

#### Scenario: Manifest covers all registered OBX codes
- **WHEN** the manifest is loaded alongside the `_CODE_METADATA` registry from `models/observation.py`
- **THEN** every code in `_CODE_METADATA` SHALL have a corresponding entry in the manifest, and no manifest entry SHALL reference a code not in the registry

#### Scenario: Manifest includes conditional codes
- **WHEN** the manifest is read
- **THEN** codes like COVERAGE_ARTICLE_COUNT (conditional on NewsAPI key) SHALL be marked as conditional with a condition description, while codes like CLAIM_TEXT SHALL be marked as mandatory

### Requirement: Full-pipeline test verifies observation code coverage
The full-pipeline integration test SHALL verify that all mandatory OBX codes from the manifest are emitted when processing a check-worthy claim with all APIs available.

#### Scenario: All mandatory codes emitted for check-worthy claim
- **WHEN** the full pipeline processes a check-worthy political claim with mocked APIs returning valid responses
- **THEN** every OBX code marked mandatory in the manifest SHALL appear at least once across all Redis observation streams, with correct agent identity and value type

#### Scenario: Conditional codes emitted when conditions are met
- **WHEN** the full pipeline processes a claim with NewsAPI key available
- **THEN** COVERAGE_ARTICLE_COUNT, COVERAGE_FRAMING, COVERAGE_TOP_SOURCE, and COVERAGE_TOP_SOURCE_URL SHALL appear in the coverage agent streams

#### Scenario: Conditional codes absent when conditions are not met
- **WHEN** the full pipeline processes a claim without NewsAPI key
- **THEN** coverage-specific codes SHALL NOT appear in Redis streams, and the test SHALL NOT flag this as a failure

### Requirement: Observation sequence follows node execution order
Observations SHALL be published in pipeline execution order: ingestion codes first, then evidence/coverage codes (interleaved due to parallelism), then validation codes, then synthesizer codes.

#### Scenario: Synthesizer observations come after validation observations
- **WHEN** observations are read from all Redis streams ordered by timestamp
- **THEN** all CONFIDENCE_SCORE, VERDICT, and VERDICT_NARRATIVE observations SHALL have timestamps strictly after all SOURCE_CONVERGENCE_SCORE and BLINDSPOT_SCORE observations

#### Scenario: Evidence and coverage observations may interleave
- **WHEN** observations are read from evidence and coverage streams
- **THEN** the test SHALL allow interleaved timestamps between evidence and coverage observations (they execute in parallel)

### Requirement: Manifest unit test detects registry drift
A unit test SHALL compare the observation manifest against `_CODE_METADATA` and fail if they diverge, ensuring the manifest stays synchronized with code changes.

#### Scenario: New code added to registry but not manifest
- **WHEN** a developer adds a new ObservationCode to `_CODE_METADATA` without updating the manifest
- **THEN** the unit test SHALL fail with a message listing the missing manifest entries

#### Scenario: Manifest entry references removed code
- **WHEN** a manifest entry references an ObservationCode that no longer exists in `_CODE_METADATA`
- **THEN** the unit test SHALL fail with a message listing the stale manifest entries
