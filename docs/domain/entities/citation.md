# Entity: Citation

## Description

A reference to a source URL together with metadata about which agent discovered it and how it was validated. Citations are aggregated into the verdict's citation list, providing users with a complete, annotated bibliography of all sources that informed the fact-check.

## Invariants

- **INV-1**: A citation must reference a non-empty source URL.
- **INV-2**: A citation must identify the agent that discovered the source.
- **INV-3**: A citation must identify the observation code that carries the source.
- **INV-4**: A citation must have a validation status from the source-validator agent.
- **INV-5**: A citation belongs to exactly one verdict.

## Value Objects

| Name | Type | Constraints |
|------|------|-------------|
| `SourceUrl` | URL | Must be a valid HTTP or HTTPS URL |
| `ValidationStatus` | Enum | `live` · `dead` · `redirect` · `soft-404` · `timeout` · `not-validated` |
| `SourceName` | string | Human-readable source name (e.g., "PolitiFact", "CDC", "Reuters") |

## Schema

```typescript
interface Citation {
  sourceUrl:        string;           // the cited URL
  sourceName:       string;           // human-readable source name
  agent:            string;           // which agent discovered this source
  observationCode:  string;           // which observation code carries this URL
  validationStatus: ValidationStatus; // from source-validator
  convergenceCount: number;           // how many agents cited this same source
}
```

## Creation Rules

- **Created by**: `FinalizeSessionUseCase` (assembles from source-validator's CITATION_LIST observation and individual agent observations)
- **Requires**: source URL, agent, observation code
- **Enriched by**: Source-validator agent (validation status, convergence count)
- **Fallback**: If source-validator did not reach a URL, validation status is `not-validated`

## Aggregate Boundary

- **Owned by**: Verdict (N:1)
- **Derived from**: Observations across all agents (COVERAGE_TOP_SOURCE_URL, CLAIMREVIEW_URL, DOMAIN_SOURCE_URL, SOURCE_EXTRACTED_URL)
