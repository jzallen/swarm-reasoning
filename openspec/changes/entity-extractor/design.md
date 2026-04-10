## Context

The entity-extractor runs in Phase 1 (sequential ingestion phase), as the third agent after ingestion-agent and claim-detector. At this point in the build:

- Slice 1 (redis-streams-observation-schema) provides `ReasoningStream`, `Observation`, `ObservationCode`, and stream message types
- The orchestrator (Temporal workflow) dispatches agent activities -- entity-extractor must implement the agent handler interface
- Fanout agents will read `ENTITY_*` observations from Redis Streams

Key constraints from architecture docs:

- **ADR-016**: Agent is a Temporal activity worker in the shared agent-service container. No per-agent MCP server or container.
- **ADR-004**: LLMs never construct raw observations. The `extract_entities` handler encodes entity values; the LLM only decides which entities exist.
- **ADR-003**: Append-only observation log -- once published, no observation is modified or deleted.
- **NFR-003**: Temporal activity dispatch latency P99 < 2 seconds. The activity itself should complete within 120 seconds (start_to_close_timeout).

## Goals / Non-Goals

**Goals:**

- Implement an agent handler that extracts entities from the normalized claim text using Claude LLM
- Use Claude LLM to identify persons, organizations, dates, locations, and statistics in the normalized claim
- Publish one observation per entity found, using the five owned OBX codes
- Emit START before any observations and STOP after all observations, following the session protocol
- Run as a Temporal activity within the shared agent-service container
- Publish progress events to `progress:{runId}` for frontend visibility
- Write unit tests for entity extraction logic and integration tests for the full START->OBS->STOP flow

**Non-Goals:**

- Entity disambiguation or coreference resolution (out of scope -- NER only, no linking to knowledge bases)
- Confidence scoring per entity (the synthesizer owns confidence; entity-extractor emits raw extractions)
- Reading observations from other agents' streams directly (entity-extractor reads `CLAIM_NORMALIZED` from claim-detector's stream)
- Batching multiple claims in a single call
- TypeScript implementation (all agents are Python)
- Per-agent Dockerfile or docker-compose entry (runs in shared container per ADR-0016)

## Decisions

### 1. Single handler with single LLM call

One handler with a single `CLAIM_NORMALIZED` input keeps the interface minimal and avoids multiple LLM round-trips. The LLM extracts all entity types in a single Claude invocation and the handler publishes all resulting observations.

**Alternative considered:** Separate handlers per entity type. Rejected -- five Temporal activity dispatches multiplies latency.

### 2. Structured output for LLM response

The Claude API call uses structured output (JSON mode) to return a typed response:

```python
class EntityExtractionResult(BaseModel):
    persons: list[str]
    organizations: list[str]
    dates: list[str]       # format: YYYYMMDD or YYYYMMDD-YYYYMMDD
    locations: list[str]
    statistics: list[str]  # e.g. "87% of adults"
```

The handler iterates each list and publishes one OBS per item. Empty lists produce no observations for that type.

**Alternative considered:** Free-form LLM output parsed with regex. Rejected -- fragile; structured output eliminates parsing failures.

### 3. One observation per entity (no batching)

Each entity is a separate `OBS` message with its own `seq` number. This satisfies the OBX registry description ("One OBX row per person") and makes observations independently addressable in the stream.

### 4. Empty entity types produce no observations

If the claim contains no statistics, no `ENTITY_STATISTIC` observations are published. The absence of observations is the signal.

### 5. Package structure (within shared agent-service)

```
services/
  agent-service/
    src/
      agents/
        entity_extractor/
          __init__.py
          handler.py       -- EntityExtractorHandler: run() entry point called by Temporal activity
          extractor.py     -- Claude LLM call, EntityExtractionResult model
          publisher.py     -- observation publishing logic (START/OBS loop/STOP)
    tests/
      unit/
        agents/
          test_extractor.py  -- mock Claude responses, verify entity lists
          test_publisher.py  -- mock ReasoningStream, verify OBS count and codes
      integration/
        agents/
          test_entity_extractor.py  -- Temporal activity with live Redis, mocked Claude
```

No per-agent Dockerfile. No per-agent docker-compose entry. The agent runs within the shared `agent-service` container.

### 6. Progress events

The agent publishes progress events to `progress:{runId}`:
- `"Extracting named entities..."` -- at start
- `"Found {n} entities: {summary}"` -- after extraction completes
- `"Entity extraction complete"` -- at STOP

## Risks / Trade-offs

- **[LLM latency]** -- Claude LLM invocation is the dominant latency contributor. Compact prompt design and low `max_tokens` (<= 512) mitigate this. If the budget is tight, the Claude haiku model class is a fallback.
- **[Structured output schema drift]** -- If the `EntityExtractionResult` Pydantic model changes, existing observations in the stream are not retroactively affected (append-only).
- **[LLM hallucination of entities]** -- The LLM may invent entities not in the claim. Mitigated by a grounding prompt instruction ("only extract entities explicitly mentioned") and verified in acceptance tests.
- **[Date format normalization]** -- ENTITY_DATE requires `YYYYMMDD` or `YYYYMMDD-YYYYMMDD` format. The LLM may return free-form dates. The publisher normalizes date strings before writing the observation; malformed dates are logged and published with a note.
