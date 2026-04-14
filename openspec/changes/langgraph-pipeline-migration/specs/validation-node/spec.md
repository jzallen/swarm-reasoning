## ADDED Requirements

### Requirement: Validation node runs procedural tool chain without LLM
The system SHALL implement a `validation_node` async function in `pipeline/nodes/validation.py` that accepts PipelineState and RunnableConfig and returns a dict with keys: validated_urls, convergence_score, citations, blindspot_score, blindspot_direction. The node SHALL execute 5 tools in fixed order: extract_source_urls, validate_urls, compute_convergence, aggregate_citations, analyze_blindspots. No LLM routing — tools are called as plain async functions.

#### Scenario: Full validation pipeline
- **WHEN** validation_node receives PipelineState with evidence and coverage data
- **THEN** it extracts URLs from all upstream sources, validates them, computes convergence across sources, aggregates citations, and analyzes blindspots

#### Scenario: Convergence score reflects source agreement
- **WHEN** evidence and coverage sources agree on the claim's veracity
- **THEN** convergence_score is above 0.7

#### Scenario: Blindspot detection with missing spectrum
- **WHEN** coverage data is missing for one political spectrum (e.g., coverage was skipped)
- **THEN** blindspot_score reflects the gap and blindspot_direction identifies the missing spectrum

### Requirement: Validation node reads all upstream data from PipelineState
The system SHALL read claimreview_matches, domain_sources, coverage_left, coverage_center, coverage_right from PipelineState. The node SHALL NOT read from Redis Streams.

#### Scenario: Validation with partial coverage data
- **WHEN** coverage_node was skipped (no NewsAPI key) and coverage fields are empty
- **THEN** validation_node processes only evidence data and marks coverage-related blindspots
