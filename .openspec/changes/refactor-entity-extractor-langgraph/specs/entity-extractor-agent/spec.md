## ADDED Requirements

### Requirement: IngestionLangGraphBase for Phase 1 agents

An `IngestionLangGraphBase` class SHALL provide a LangGraph ReAct agent base for Phase 1 (ingestion) agents, mirroring `LangGraphBase` but using INGESTION phase lifecycle and reading only from the claim-detector stream.

#### Scenario: Phase 1 lifecycle management
- **WHEN** an `IngestionLangGraphBase` subclass is invoked via `run()`
- **THEN** it SHALL publish START (phase=INGESTION), execute the LangGraph agent, and publish STOP with observation count and final status

#### Scenario: Upstream context loading
- **WHEN** loading upstream context
- **THEN** it SHALL read `CLAIM_NORMALIZED` from the claim-detector stream and pass the normalized claim text to the agent

#### Scenario: Heartbeat and progress
- **WHEN** executing
- **THEN** it SHALL send Temporal heartbeats every 10 seconds and publish progress events to `progress:{runId}`

#### Scenario: Timeout enforcement
- **WHEN** execution exceeds the internal timeout (30 seconds)
- **THEN** it SHALL cancel the agent, publish a timeout observation with status `X`, and set final status to `X`

### Requirement: Entity-extractor as LangGraph agent

The entity-extractor handler SHALL extend `IngestionLangGraphBase` and use the existing `extract_entities` tool from `tools.py`.

#### Scenario: Standard entity extraction
- **WHEN** invoked with a run_id
- **THEN** the agent SHALL call `extract_entities` with the normalized claim text and publish `ENTITY_*` observations in deterministic order (PERSON, ORG, DATE, LOCATION, STATISTIC)

#### Scenario: Model selection
- **WHEN** constructing the LangGraph agent
- **THEN** it SHALL use `claude-haiku-4-5` as the agent model (overriding the Sonnet default)

#### Scenario: Anthropic client injection
- **WHEN** the `extract_entities` tool is invoked
- **THEN** the `AsyncAnthropic` client SHALL be available via `AgentContext.anthropic_client` for the NER LLM call

#### Scenario: Empty extraction
- **WHEN** the claim contains no extractable entities
- **THEN** the agent SHALL publish START and STOP with `observationCount=0` and `finalStatus=F`

#### Scenario: LLM failure
- **WHEN** the Anthropic API call fails with a retryable error
- **THEN** the handler SHALL raise the error for Temporal retry after publishing STOP with `finalStatus=X`

### Requirement: Agent registration

The entity-extractor handler SHALL be registered with `@register_handler("entity-extractor")` so the Temporal activity dispatcher can look it up by name.

#### Scenario: Handler lookup
- **WHEN** `get_agent_handler("entity-extractor")` is called
- **THEN** it SHALL return an instance of the new LangGraph-based handler
