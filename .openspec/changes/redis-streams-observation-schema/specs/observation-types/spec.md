## ADDED Requirements

### Requirement: OBX code enum covers all 36 registry codes
The system SHALL define an `ObservationCode` enum containing all 36 codes from `docs/domain/obx-code-registry.json`. Each enum member SHALL carry metadata: display name, owner agent, value type, units, and reference range.

#### Scenario: All registry codes are represented
- **WHEN** the OBX code registry JSON is loaded
- **THEN** every code in the registry has a corresponding `ObservationCode` enum member

#### Scenario: Unknown code rejected
- **WHEN** an observation is constructed with a code not in the enum
- **THEN** a validation error is raised

### Requirement: Epistemic status enum with transition validation
The system SHALL define an `EpistemicStatus` enum with values P (preliminary), F (final), C (corrected), X (cancelled). Status transitions SHALL be validated: P→F, P→X, F→C, C→C are valid; all other transitions SHALL raise `InvalidStatusTransition`.

#### Scenario: Valid transition P to F
- **WHEN** a status transition from P to F is requested
- **THEN** the transition succeeds

#### Scenario: Invalid transition F to P
- **WHEN** a status transition from F to P is requested
- **THEN** an `InvalidStatusTransition` error is raised

#### Scenario: Corrected can self-transition
- **WHEN** a status transition from C to C is requested
- **THEN** the transition succeeds

### Requirement: Observation model with full field validation
The system SHALL define an `Observation` Pydantic model with fields: runId, agent, seq (positive int), code (ObservationCode), value (string), valueType (ST|NM|CWE|TX), units (optional), referenceRange (optional), status (EpistemicStatus), timestamp (ISO 8601 UTC), method (string), note (optional). The model SHALL validate that valueType matches the code's registered value type.

#### Scenario: Valid observation serializes to JSON
- **WHEN** a valid Observation is created and serialized
- **THEN** the JSON output contains all required fields with correct types

#### Scenario: Value type mismatch rejected
- **WHEN** an Observation is created with code CONFIDENCE_SCORE (NM) but valueType ST
- **THEN** a validation error is raised

#### Scenario: Seq must be positive
- **WHEN** an Observation is created with seq=0 or seq=-1
- **THEN** a validation error is raised

### Requirement: Stream message types (START, OBS, STOP)
The system SHALL define three message models: `StartMessage` (type, runId, agent, phase, timestamp), `ObsMessage` (type, observation: Observation), `StopMessage` (type, runId, agent, finalStatus: F|X, observationCount, timestamp). A `StreamMessage` union type SHALL discriminate on the `type` field.

#### Scenario: START message construction
- **WHEN** a StartMessage is created with valid fields
- **THEN** the `type` field is "START" and `phase` is one of ingestion/fanout/synthesis

#### Scenario: STOP message finalStatus restricted
- **WHEN** a StopMessage is created with finalStatus P
- **THEN** a validation error is raised (only F or X allowed)

#### Scenario: StreamMessage discriminated union
- **WHEN** a JSON string with `"type": "OBS"` is deserialized as StreamMessage
- **THEN** the result is an ObsMessage instance

### Requirement: Value type discriminators
The system SHALL define value types: ST (string, any text), NM (numeric, parseable as float), CWE (coded, format `CODE^Display^CodingSystem`), TX (text, >200 chars). Validation SHALL enforce format constraints per type.

#### Scenario: NM value must be numeric
- **WHEN** an observation with valueType NM and value "not-a-number" is created
- **THEN** a validation error is raised

#### Scenario: CWE value must follow coded format
- **WHEN** an observation with valueType CWE and value "SUPPORTIVE^Supportive^FCK" is created
- **THEN** validation succeeds

#### Scenario: TX value must exceed 200 characters
- **WHEN** an observation with valueType TX and a 50-character value is created
- **THEN** a validation error is raised
