## ADDED Requirements

### Requirement: Aggregate citations from all evidence agents

The source-validator agent SHALL aggregate all extracted URLs with their validation status, originating agent, observation code, source name, and convergence count into a structured citation list. Each unique (url, agent, observationCode) tuple produces one citation entry.

Citation object schema (per docs/domain/entities/citation.md):

```typescript
interface Citation {
    sourceUrl:        string;           // the cited URL
    sourceName:       string;           // human-readable source name
    agent:            string;           // which agent discovered this source
    observationCode:  string;           // which observation code carries this URL
    validationStatus: string;           // from URL validation: live, dead, redirect, soft-404, timeout, not-validated
    convergenceCount: number;           // how many distinct agents cited this same normalized source
}
```

#### Scenario: Full citation list from 5 agents

- **GIVEN** 5 URLs extracted from 5 agents, all validated as LIVE, no convergence
- **WHEN** citation aggregation runs
- **THEN** CITATION_LIST contains 5 citation objects
- **AND** each has validationStatus = "live" and convergenceCount = 1

#### Scenario: URL cited by multiple agents produces multiple citations

- **GIVEN** "https://www.cdc.gov/covid/data/" is cited by both coverage-center (COVERAGE_TOP_SOURCE_URL) and domain-evidence (DOMAIN_SOURCE_URL)
- **WHEN** citation aggregation runs
- **THEN** CITATION_LIST contains 2 citation objects for this URL (one per agent/code pair)
- **AND** both have convergenceCount = 2 (since 2 agents cite the same normalized source)

---

### Requirement: Validation status mapping to Citation

The validation status in the citation list SHALL use lowercase string values matching the `ValidationStatus` enum from docs/domain/entities/citation.md:
- LIVE -> "live"
- DEAD -> "dead"
- REDIRECT -> "redirect"
- SOFT404 -> "soft-404"
- TIMEOUT -> "timeout"
- Not validated (URL could not be reached during validation) -> "not-validated"

#### Scenario: Mixed validation statuses in citation list

- **GIVEN** 3 URLs: one LIVE, one DEAD, one TIMEOUT
- **WHEN** citation aggregation runs
- **THEN** citation objects have validationStatus values: "live", "dead", "timeout"

---

### Requirement: Missing validation fallback

If a URL was extracted but not validated (e.g., URL validation timed out at the activity level before reaching this URL), the citation SHALL have validationStatus = "not-validated" (per docs/domain/entities/citation.md creation rules).

#### Scenario: URL not reached during validation

- **GIVEN** 15 URLs extracted but activity timeout fired after validating only 10
- **WHEN** citation aggregation runs
- **THEN** 10 citations have their actual validation status
- **AND** 5 citations have validationStatus = "not-validated"

---

### Requirement: CITATION_LIST observation

The agent SHALL publish one CITATION_LIST observation (TX type, status = F) whose value is a JSON-encoded array of citation objects. The JSON array is sorted by agent name alphabetically, then by observationCode. The observation is published via the `publish_observation` tool (ADR-0004).

#### Scenario: CITATION_LIST published as valid JSON

- **GIVEN** 4 citations aggregated
- **WHEN** the observation is published
- **THEN** CITATION_LIST value is a valid JSON string
- **AND** `json.loads(value)` returns a list of 4 dicts
- **AND** each dict has keys: sourceUrl, sourceName, agent, observationCode, validationStatus, convergenceCount

#### Scenario: Empty citation list

- **GIVEN** no URLs were extracted (all agents had 0 articles or no match)
- **WHEN** the observation is published
- **THEN** CITATION_LIST value = "[]" (empty JSON array)
- **AND** status = F (empty list is a valid result, not a failure)

---

### Requirement: Citation list consumed by synthesizer

The CITATION_LIST observation SHALL be consumed by the synthesizer agent for verdict annotation. The synthesizer reads the CITATION_LIST from `reasoning:{runId}:source-validator` and includes the citations in the verdict response. Per ADR-0021, the citation list provides users with a complete, annotated bibliography of all sources that informed the fact-check.

#### Scenario: Synthesizer reads CITATION_LIST

- **GIVEN** source-validator has published CITATION_LIST with 5 citations
- **WHEN** the synthesizer resolves observations from all 10 upstream streams
- **THEN** CITATION_LIST is included in the resolved observation set
- **AND** the synthesizer uses the citations to annotate the verdict with source URLs and validation statuses

---

### Requirement: Progress event for citation aggregation

The agent SHALL publish a progress event to `progress:{runId}` upon completing citation aggregation: "Aggregated {n} source citations" or "No source citations found".

#### Scenario: Citation aggregation progress

- **GIVEN** 6 citations aggregated
- **WHEN** aggregation completes
- **THEN** progress event = "Aggregated 6 source citations"
