## ADDED Requirements

### Requirement: Extract URLs from cross-agent observation data

The source-validator agent SHALL extract URLs from the cross-agent observation data provided as Temporal activity input by the orchestrator workflow. The orchestrator reads URL-typed observation values from other agents' Redis Streams and passes them in the `cross_agent_data.urls` field of `FanoutActivityInput`.

URL observation codes to extract from:
- `COVERAGE_TOP_SOURCE_URL` (coverage-left, coverage-center, coverage-right) -- up to 3 URLs
- `CLAIMREVIEW_URL` (claimreview-matcher) -- 0 or 1 URL
- `DOMAIN_SOURCE_URL` (domain-evidence) -- 0 or 1 URL

Each extracted URL entry includes the source agent name, observation code, and human-readable source name (from the corresponding COVERAGE_TOP_SOURCE, CLAIMREVIEW_SOURCE, or DOMAIN_SOURCE_NAME observation).

#### Scenario: Full extraction from all agents

- **GIVEN** cross_agent_data contains URLs from coverage-left (Reuters), coverage-center (AP), coverage-right (Fox News), claimreview-matcher (PolitiFact), and domain-evidence (CDC)
- **WHEN** link extraction runs
- **THEN** 5 ExtractedUrl objects are produced
- **AND** each has the correct agent, observationCode, and sourceName fields

#### Scenario: Partial extraction when some agents have no URLs

- **GIVEN** cross_agent_data contains URLs from coverage-center only (other agents had 0 articles or no match)
- **WHEN** link extraction runs
- **THEN** 1 ExtractedUrl object is produced
- **AND** extraction completes without error

#### Scenario: Empty cross-agent data

- **GIVEN** cross_agent_data.urls is an empty list
- **WHEN** link extraction runs
- **THEN** 0 ExtractedUrl objects are produced
- **AND** no error is raised

---

### Requirement: URL deduplication by exact match

The agent SHALL deduplicate extracted URLs by exact string match. When multiple agents cite the exact same URL, a single ExtractedUrl is retained but all agent/code associations are preserved for convergence tracking.

#### Scenario: Same URL from two agents

- **GIVEN** coverage-left and domain-evidence both cite "https://www.cdc.gov/covid/data/"
- **WHEN** deduplication runs
- **THEN** one unique URL entry is produced
- **AND** both agent associations (coverage-left, domain-evidence) are preserved

---

### Requirement: URL filtering

The agent SHALL reject non-HTTP/HTTPS URLs and URLs pointing to localhost or private IP ranges (10.x, 172.16-31.x, 192.168.x). Rejected URLs are logged at WARNING level and skipped.

#### Scenario: Malformed URL rejected

- **GIVEN** an observation contains the value "not-a-url"
- **WHEN** extraction processes this entry
- **THEN** the entry is skipped
- **AND** a WARNING is logged

#### Scenario: Localhost URL rejected

- **GIVEN** an observation contains "http://localhost:8080/test"
- **WHEN** extraction processes this entry
- **THEN** the entry is skipped

---

### Requirement: SOURCE_EXTRACTED_URL observations

For each unique extracted URL, the agent SHALL publish one SOURCE_EXTRACTED_URL observation (ST type, status = F) to its stream. The value is the full URL string. Observations are published via the `publish_observation` tool (ADR-0004).

#### Scenario: Three URLs extracted produces three observations

- **GIVEN** link extraction produces 3 unique URLs
- **WHEN** observations are published
- **THEN** 3 SOURCE_EXTRACTED_URL observations are emitted with seq starting at 1
- **AND** each has status = F and agent = "source-validator"
