## ADDED Requirements

### Requirement: Standalone context loading function
A standalone async function `load_claim_context(stream, run_id) -> ClaimContext` SHALL exist in `agents/context.py`. It SHALL read Phase 1 streams (claim-detector, ingestion-agent, entity-extractor) and assemble a `ClaimContext` with normalized claim, domain, and entities.

#### Scenario: Phase 2 agent loads context
- **WHEN** a Phase 2 agent (e.g., coverage-left) needs upstream context
- **THEN** it SHALL call `load_claim_context()` directly, not inherit FanoutBase for context access

#### Scenario: Phase 1 agent skips context
- **WHEN** a Phase 1 agent (e.g., claim-detector) executes
- **THEN** it SHALL NOT call `load_claim_context()` since no upstream context exists

#### Scenario: Missing upstream stream
- **WHEN** `load_claim_context()` cannot find a required upstream stream (e.g., claim-detector stream missing)
- **THEN** it SHALL raise `StreamNotFoundError` from `agents/_utils.py`

### Requirement: FanoutBase decoupled from context loading
`FanoutBase` SHALL NOT contain context loading logic. The `_load_upstream_context()` method SHALL be removed from `FanoutBase`.

#### Scenario: FanoutBase has no context method
- **WHEN** inspecting `FanoutBase` class members
- **THEN** no method named `_load_upstream_context` SHALL exist
