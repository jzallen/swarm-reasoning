## ADDED Requirements

### Requirement: URL normalization for convergence comparison

The source-validator agent SHALL normalize URLs before comparing them for convergence. Normalization applies the following transformations:
1. Parse with `urllib.parse.urlparse`
2. Lowercase the scheme and netloc
3. Strip `www.` prefix from netloc
4. Remove query parameters and fragments
5. Remove trailing slashes from path
6. Reconstruct as `{scheme}://{netloc}{path}`

This captures cases where multiple agents cite the same underlying source with different query parameters, fragments, or www prefixes.

#### Scenario: URLs with different query params normalize to the same source

- **GIVEN** coverage-left cites "https://www.cdc.gov/covid/data/?page=1"
- **AND** domain-evidence cites "https://cdc.gov/covid/data/#section2"
- **WHEN** normalization runs
- **THEN** both normalize to "https://cdc.gov/covid/data"
- **AND** they are treated as the same source for convergence

#### Scenario: Different paths are not merged

- **GIVEN** one URL is "https://reuters.com/world/article1"
- **AND** another is "https://reuters.com/business/article2"
- **WHEN** normalization runs
- **THEN** they normalize to different URLs
- **AND** they are treated as distinct sources

---

### Requirement: Convergence score computation

The agent SHALL compute SOURCE_CONVERGENCE_SCORE as:

```
converging_count = count of normalized URLs cited by 2+ distinct agents
total_unique_count = count of unique normalized URLs
score = converging_count / total_unique_count (0.0 if total_unique_count == 0)
```

The score is rounded to 4 decimal places and clamped to [0.0, 1.0].

Per ADR-0021: "source convergence across agents is a strong signal for confidence scoring."

#### Scenario: No convergence (all unique)

- **GIVEN** 5 URLs, each cited by exactly one agent
- **WHEN** convergence scoring runs
- **THEN** SOURCE_CONVERGENCE_SCORE = 0.0

#### Scenario: Partial convergence

- **GIVEN** 4 unique normalized URLs
- **AND** 2 of them are cited by 2+ agents
- **WHEN** convergence scoring runs
- **THEN** SOURCE_CONVERGENCE_SCORE = 0.5 (2/4)

#### Scenario: Full convergence

- **GIVEN** 3 unique normalized URLs
- **AND** all 3 are cited by 2+ agents
- **WHEN** convergence scoring runs
- **THEN** SOURCE_CONVERGENCE_SCORE = 1.0

#### Scenario: No URLs extracted

- **GIVEN** no URLs in cross_agent_data
- **WHEN** convergence scoring runs
- **THEN** SOURCE_CONVERGENCE_SCORE = 0.0

#### Scenario: Single URL from single agent

- **GIVEN** 1 URL cited by 1 agent
- **WHEN** convergence scoring runs
- **THEN** SOURCE_CONVERGENCE_SCORE = 0.0 (no multi-agent citation)

---

### Requirement: Convergence count per URL

For each extracted URL, the agent SHALL compute a convergence count: the number of distinct agents that cite the same normalized URL. This count is included in the CITATION_LIST entries.

#### Scenario: CDC URL cited by 3 agents

- **GIVEN** coverage-center, domain-evidence, and claimreview-matcher all cite URLs normalizing to "https://cdc.gov/covid/data"
- **WHEN** convergence analysis runs
- **THEN** the convergence count for this normalized URL is 3

---

### Requirement: SOURCE_CONVERGENCE_SCORE observation

The agent SHALL publish one SOURCE_CONVERGENCE_SCORE observation (NM type, value in [0.0, 1.0], status = F). This observation is consumed by the synthesizer for confidence scoring and by the blindspot-detector as additional input.

#### Scenario: Convergence score published

- **GIVEN** convergence scoring produces 0.5
- **WHEN** the observation is published
- **THEN** SOURCE_CONVERGENCE_SCORE has value "0.5", valueType = "NM", units = "score", referenceRange = "0.0-1.0", status = F
- **AND** agent = "source-validator"
