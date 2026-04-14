## ADDED Requirements

### Requirement: PipelineState TypedDict defines all inter-node data
The system SHALL define a `PipelineState` TypedDict in `pipeline/state.py` that contains typed fields for all inputs, phase outputs, metadata, and error tracking. Each field SHALL have a type annotation. The state SHALL cover: claim input (claim_text, claim_url, submission_date, run_id, session_id), intake output (normalized_claim, claim_domain, check_worthy_score, entities, is_check_worthy), evidence output (claimreview_matches, domain_sources, evidence_confidence), coverage output (coverage_left, coverage_center, coverage_right, framing_analysis), validation output (validated_urls, convergence_score, citations, blindspot_score, blindspot_direction), synthesizer output (verdict, confidence, narrative, verdict_observations), and metadata (observations list, errors list).

#### Scenario: PipelineState construction with minimal input
- **WHEN** a PipelineState is constructed with claim_text, run_id, and session_id
- **THEN** the state object is valid and all output fields default to empty/None values

#### Scenario: PipelineState carries intake output to downstream nodes
- **WHEN** the intake node returns a dict with normalized_claim, entities, and is_check_worthy
- **THEN** LangGraph merges these into PipelineState and downstream nodes can read them

### Requirement: PipelineContext provides shared runtime dependencies
The system SHALL define a `PipelineContext` dataclass in `pipeline/context.py` containing: Redis stream client, run_id, session_id, heartbeat callback function, and an `publish_observations(agent_name, observations)` async method. PipelineContext SHALL be passed to nodes via LangGraph's `RunnableConfig` configurable dict.

#### Scenario: PipelineContext accessible from any node
- **WHEN** a pipeline node receives `config: RunnableConfig`
- **THEN** calling `_get_pipeline_context(config)` returns a PipelineContext with a valid stream client and run_id

#### Scenario: PipelineContext publishes observations to Redis
- **WHEN** `ctx.publish_observations("intake", observations)` is called
- **THEN** observations are published to Redis stream key `reasoning:{run_id}:intake` with START, observation entries, and STOP markers
