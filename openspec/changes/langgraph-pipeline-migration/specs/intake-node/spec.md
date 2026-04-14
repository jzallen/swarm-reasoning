## ADDED Requirements

### Requirement: Intake node consolidates ingestion, claim-detection, and entity-extraction
The system SHALL implement an `intake_node` async function in `pipeline/nodes/intake.py` that accepts PipelineState and RunnableConfig and returns a dict with keys: normalized_claim, claim_domain, check_worthy_score, entities, is_check_worthy. The node SHALL use 5 tools: validate_claim, classify_domain, normalize_claim, score_check_worthiness, extract_entities.

#### Scenario: Successful intake processing
- **WHEN** intake_node receives a PipelineState with claim_text "The unemployment rate is 3.5%"
- **THEN** the returned dict contains a normalized_claim string, a claim_domain string, a check_worthy_score float between 0 and 1, an entities dict with person/org/date/location/statistic keys, and is_check_worthy as a boolean

#### Scenario: Not check-worthy claim
- **WHEN** intake_node processes a claim with check_worthy_score below the threshold
- **THEN** is_check_worthy is False, and the fan-out router routes directly to synthesizer

### Requirement: Intake node publishes observations to Redis
The system SHALL publish observations to Redis via PipelineContext after processing. Stream key format SHALL be `reasoning:{run_id}:intake`.

#### Scenario: Intake observations appear in Redis
- **WHEN** intake_node completes processing
- **THEN** the Redis stream `reasoning:{run_id}:intake` contains START, one or more observations with OBX codes from the intake agent's registry, and STOP
