## ADDED Requirements

### Requirement: Coverage node searches news across three political spectra
The system SHALL implement a `coverage_node` async function in `pipeline/nodes/coverage.py` that accepts PipelineState and RunnableConfig and returns a dict with keys: coverage_left, coverage_center, coverage_right, framing_analysis. The node SHALL use 3 parameterized tools: search_news(spectrum), detect_framing, select_top_source.

#### Scenario: Coverage across all spectra
- **WHEN** coverage_node processes a political claim
- **THEN** coverage_left, coverage_center, and coverage_right each contain a list of source dicts with title, url, publisher, and spectrum fields

#### Scenario: Framing analysis produced
- **WHEN** coverage_node completes news search across all spectra
- **THEN** framing_analysis contains a dict with framing differences and bias indicators across the three spectra

### Requirement: Coverage node is conditionally skipped
The system SHALL skip the coverage node when the NewsAPI key is not configured. The fan-out router SHALL exclude the `Send("coverage", state)` call when `has_newsapi_key()` returns False.

#### Scenario: No NewsAPI key configured
- **WHEN** the NEWSAPI_KEY environment variable is not set
- **THEN** the fan-out router dispatches only to evidence_node, and coverage fields in PipelineState remain empty

### Requirement: Coverage directory consolidation
The system SHALL consolidate the three coverage handler directories (coverage_left/, coverage_center/, coverage_right/) into a single coverage/ directory with parameterized tools and per-spectrum source configuration files at coverage/sources/{left,center,right}.json.

#### Scenario: Single coverage directory replaces three
- **WHEN** the migration is complete
- **THEN** no coverage_left/, coverage_center/, or coverage_right/ directories exist, and coverage/sources/ contains left.json, center.json, and right.json
