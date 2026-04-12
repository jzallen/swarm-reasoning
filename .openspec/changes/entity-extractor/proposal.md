## Why

The claim-detector produces a normalized claim text. That text contains named entities -- persons, organizations, dates, locations, and statistics -- which every downstream agent needs to scope their evidence gathering. Without extracted entities, coverage agents must parse the raw claim themselves (error-prone duplication), and the synthesizer lacks the entity context required to compare evidence across sources.

The entity-extractor is the third sequential step in Phase 1 (ingestion -> claim-detector -> entity-extractor). It must complete before the parallel fanout agents can begin. Delaying this slice delays the entire fanout phase.

## What Changes

- Implement the `entity-extractor` as a Temporal activity worker within the shared Python agent-service container (ADR-0016)
- The agent invokes a Claude LLM to run NER over the normalized claim text within the Temporal activity execution
- For each entity found, the tool publishes one OBS message per entity to the Redis Stream
- Five OBX codes are owned by this agent: `ENTITY_PERSON`, `ENTITY_ORG`, `ENTITY_DATE`, `ENTITY_LOCATION`, `ENTITY_STATISTIC`
- If no entities of a given type are found, no observations are published for that type (empty list, not a negative assertion)
- Publish progress events to `progress:{runId}` for SSE relay to the frontend
- All observations are published via tool-based construction (ADR-004) -- the LLM never writes raw JSON observations

## Capabilities

### New Capabilities

- `entity-recognition`: Named entity recognition via Claude LLM for five entity types. The `ClaimVerificationWorkflow` dispatches the `entity-extractor` Temporal activity with a runId. The agent reads `CLAIM_NORMALIZED` from the claim-detector's stream, extracts entities, publishes a START message, one OBS per entity found (one observation per entity, not batched), then a STOP message. Total activity execution must complete within the Temporal `start_to_close_timeout` (120 s). Temporal activity dispatch latency must be under 2 seconds P99 (NFR-003).

### Modified Capabilities

None. This slice introduces a new agent with no changes to existing components.

## Impact

- **New module**: `services/agent-service/src/agents/entity_extractor/` (Python, within shared agent-service container)
- **Temporal activity**: registered as `entity-extractor` activity in the agent-service worker; dispatched by `ClaimVerificationWorkflow` as the third activity in Phase 1
- **No per-agent container**: runs in the shared agent-service container alongside all other agent workers (ADR-0016)
- **Dependencies**: `anthropic` SDK (Claude LLM), `swarm_reasoning` package (slice 1)
- **Upstream dependency**: Reads `CLAIM_NORMALIZED` from `reasoning:{runId}:claim-detector` stream
- **Downstream unblocked**: fanout agents read `ENTITY_*` observations to scope their evidence queries; synthesizer uses entity context for verdict construction
- **No changes** to existing packages, API, or orchestrator in this slice
