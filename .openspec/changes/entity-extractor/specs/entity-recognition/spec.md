# Capability: entity-recognition

## Purpose

Extract named entities from a normalized claim text using Claude LLM. Publish one observation per entity to the agent's Redis Stream. The agent runs as a Temporal activity worker within the shared Python agent-service container (ADR-0016).

---

## ADDED Requirements

### Requirement: Agent registered as Temporal activity handler

The entity-extractor SHALL be registered in the agent registry within the shared agent-service container. The `run_agent_activity` Temporal activity SHALL look up and invoke the `EntityExtractorHandler` by the name `"entity-extractor"`. No per-agent MCP server, Dockerfile, or docker-compose entry is created.

#### Scenario: Handler registered at worker startup
- **GIVEN** the agent-service Temporal worker is started
- **WHEN** the worker initializes its agent registry
- **THEN** a handler named `entity-extractor` is registered and callable

#### Scenario: Handler rejects missing upstream stream
- **WHEN** the handler is called with a run_id whose claim-detector stream does not exist
- **THEN** a `StreamNotFound` error is raised (non-retryable)

---

### Requirement: Claude LLM performs NER over normalized claim

When the handler is invoked, the agent SHALL read `CLAIM_NORMALIZED` from `reasoning:{runId}:claim-detector` and call the Claude API with a grounded NER prompt. The prompt SHALL instruct Claude to extract only entities explicitly present in the claim text. The response SHALL be parsed as `EntityExtractionResult` with five typed lists: `persons`, `organizations`, `dates`, `locations`, `statistics`. The Claude invocation SHALL use structured output (JSON mode) to guarantee parseable responses.

#### Scenario: Persons extracted from claim
- **GIVEN** the normalized claim is "senator john mccain voted against the bill in 2017"
- **WHEN** the entity-extractor activity runs
- **THEN** the `persons` list contains "John McCain"
- **AND** the `dates` list contains a value representing 2017
- **AND** the `statistics` list is empty

#### Scenario: Organization extracted from claim
- **GIVEN** the normalized claim is "the cdc reported that 70% of hospitals lack adequate staffing"
- **WHEN** the entity-extractor activity runs
- **THEN** the `organizations` list contains "CDC"
- **AND** the `statistics` list contains "70% of hospitals"

#### Scenario: No entities in claim produces all-empty lists
- **GIVEN** the normalized claim is "the weather is nice today"
- **WHEN** the entity-extractor activity runs
- **THEN** all five lists are empty
- **AND** STOP has observationCount=0

#### Scenario: Claude API failure raises retryable error
- **GIVEN** the Claude API is unreachable
- **WHEN** the entity-extractor activity runs
- **THEN** the activity raises a retryable error
- **AND** Temporal retries the activity up to 3 times with exponential backoff
- **AND** if START was published, a STOP with `finalStatus="X"` is published before the error is raised

---

### Requirement: One observation published per entity

For each entity in the extraction result, the agent SHALL publish exactly one OBS message to the Redis stream keyed `reasoning:{runId}:entity-extractor`. Each OBS message SHALL carry an `Observation` with:

- `code`: one of `ENTITY_PERSON`, `ENTITY_ORG`, `ENTITY_DATE`, `ENTITY_LOCATION`, `ENTITY_STATISTIC`
- `value`: the extracted entity string
- `valueType`: `ST`
- `status`: `P` (preliminary -- entities are extracted claims, not verified facts)
- `seq`: monotonically increasing integer starting at 1, across all entity types

Entity types SHALL be published in a deterministic order: PERSON, ORG, DATE, LOCATION, STATISTIC. Within each type, entities SHALL be published in the order returned by the LLM.

#### Scenario: Multiple persons produce multiple observations
- **GIVEN** the claim contains two persons: "Barack Obama" and "Joe Biden"
- **WHEN** the entity-extractor activity runs
- **THEN** two OBS messages with code `ENTITY_PERSON` are published
- **AND** the first has `seq=1`, the second has `seq=2`
- **AND** no batching occurs (two separate stream entries)

#### Scenario: Empty entity type produces no observations
- **GIVEN** the claim contains no statistics
- **WHEN** the entity-extractor activity runs
- **THEN** no OBS message with code `ENTITY_STATISTIC` is published

#### Scenario: Observation seq is globally monotonic
- **GIVEN** the claim yields 2 persons and 1 organization
- **WHEN** the entity-extractor activity runs
- **THEN** the ENTITY_PERSON observations have seq 1 and 2
- **AND** the ENTITY_ORG observation has seq 3

---

### Requirement: START and STOP messages bracket all observations

Before publishing any OBS messages, the agent SHALL publish a START message with `agent="entity-extractor"` and `phase="ingestion"`. After all OBS messages are published, the agent SHALL publish a STOP message with `finalStatus="F"` (if successful) or `finalStatus="X"` (if the Claude call failed after stream was opened). The START and STOP messages SHALL use the `ReasoningStream` interface from slice 1.

#### Scenario: Successful session has START before any OBS
- **WHEN** the entity-extractor activity completes successfully
- **THEN** the first message in `reasoning:{runId}:entity-extractor` is a START message
- **AND** all OBS messages follow the START message in stream order

#### Scenario: Successful session ends with STOP finalStatus F
- **WHEN** the entity-extractor activity completes without error
- **THEN** the last message in `reasoning:{runId}:entity-extractor` is a STOP message with `finalStatus="F"`
- **AND** `observationCount` in the STOP message equals the total number of OBS messages published

#### Scenario: Failed session after START emits STOP with finalStatus X
- **GIVEN** the START message was published successfully
- **AND** the Claude API call subsequently fails
- **THEN** a STOP message with `finalStatus="X"` is published before the activity raises the error

---

### Requirement: ENTITY_DATE values normalized to YYYYMMDD format

Date entities extracted by the LLM SHALL be normalized to `YYYYMMDD` (single date) or `YYYYMMDD-YYYYMMDD` (date range) before being written as observation values. This matches the format specified in `obx-code-registry.json` for `ENTITY_DATE`. If a date string cannot be normalized (e.g., "sometime last year"), the entity SHALL be published with the raw string and a `note` field of `"date-not-normalized"`.

#### Scenario: Named year normalized to YYYYMMDD range
- **GIVEN** the LLM returns date "2017"
- **WHEN** the publisher normalizes the date
- **THEN** the observation value is "20170101-20171231"

#### Scenario: Unresolvable date published with note
- **GIVEN** the LLM returns date "sometime last year"
- **WHEN** the publisher attempts normalization
- **THEN** the observation value is "sometime last year"
- **AND** the observation `note` field is "date-not-normalized"

---

### Requirement: Temporal activity completes within timeout

The `entity-extractor` activity SHALL complete within the `start_to_close_timeout` (120 seconds). The Claude API call SHALL use `max_tokens=512` and a compact prompt (<= 200 tokens). The activity SHALL heartbeat every 10 seconds via `activity.heartbeat()`. Temporal activity dispatch latency must be under 2 seconds P99 (NFR-003).

#### Scenario: Activity completes under normal conditions
- **GIVEN** the Claude API is healthy and Redis is healthy
- **WHEN** the entity-extractor activity runs with a 50-word claim
- **THEN** the activity completes within 120 seconds

#### Scenario: Claude haiku fallback for latency
- **GIVEN** configuration sets `MODEL_ID=claude-haiku-4-5`
- **WHEN** the entity-extractor activity runs
- **THEN** the agent uses the haiku model

---

### Requirement: Progress events published

The agent SHALL publish progress events to `progress:{runId}` at key milestones:
- `"Extracting named entities..."` at start
- `"Found {n} entities: {summary}"` after extraction completes (e.g., "Found 3 entities: 1 person, 1 org, 1 date")
- `"Entity extraction complete"` at STOP

#### Scenario: Progress events visible in stream
- **WHEN** the entity-extractor activity completes successfully
- **THEN** the `progress:{runId}` stream contains at least 3 progress events from the entity-extractor
