## ADDED Requirements

### Requirement: Corpus fixture covers all five ADR-0008 categories

The system SHALL provide a committed corpus fixture at `docs/validation/corpus.json` containing exactly 50 claims. The fixture SHALL include entries from each of the five ADR-0008 categories: `TRUE_MOSTLY_TRUE` (10 claims), `FALSE_PANTS_FIRE` (10 claims), `HALF_TRUE` (10 claims), `CLAIMREVIEW_INDEXED` (10 claims), and `NOT_CLAIMREVIEW_INDEXED` (10 claims). The `CLAIMREVIEW_INDEXED` and `NOT_CLAIMREVIEW_INDEXED` categories SHALL be mutually exclusive. Claims in the `CLAIMREVIEW_INDEXED` and `NOT_CLAIMREVIEW_INDEXED` categories SHALL overlap with the verdict-tier categories (TRUE_MOSTLY_TRUE, FALSE_PANTS_FIRE, HALF_TRUE).

#### Scenario: Corpus file exists and is valid JSON

- **GIVEN** the repository is checked out
- **WHEN** `docs/validation/corpus.json` is parsed
- **THEN** the file is valid JSON
- **AND** the top-level object has a `claims` array of exactly 50 entries
- **AND** the top-level object has a `version` string field

#### Scenario: Each corpus entry has required fields

- **WHEN** each entry in the `claims` array is inspected
- **THEN** each entry has: `id` (string), `claim_text` (string), `ground_truth` (one of TRUE/MOSTLY_TRUE/HALF_TRUE/MOSTLY_FALSE/FALSE/PANTS_FIRE), `categories` (array of one or more category labels), `politifact_url` (string URL), `captured_date` (YYYY-MM-DD), `speaker` (string), `domain` (controlled vocabulary)

#### Scenario: Category distribution satisfies ADR-0008

- **WHEN** the corpus is grouped by category label
- **THEN** exactly 10 entries carry `TRUE_MOSTLY_TRUE`
- **AND** exactly 10 entries carry `FALSE_PANTS_FIRE`
- **AND** exactly 10 entries carry `HALF_TRUE`
- **AND** exactly 10 entries carry `CLAIMREVIEW_INDEXED`
- **AND** exactly 10 entries carry `NOT_CLAIMREVIEW_INDEXED`
- **AND** no entry carries both `CLAIMREVIEW_INDEXED` and `NOT_CLAIMREVIEW_INDEXED`

#### Scenario: Corpus entries have distinct claim IDs

- **WHEN** all `id` fields are collected
- **THEN** all 50 IDs are distinct

### Requirement: Corpus fixture schema is validated at load time

The harness SHALL validate the corpus fixture against a JSON Schema at startup. Any schema violation SHALL cause the harness to abort with a human-readable error message before submitting any claims.

#### Scenario: Valid corpus passes schema validation

- **GIVEN** a corpus JSON file matching the required schema
- **WHEN** the harness loads the corpus
- **THEN** no validation error is raised
- **AND** the harness reports "Corpus loaded: 50 claims across 5 categories"

#### Scenario: Missing required field causes abort

- **GIVEN** a corpus entry missing the `ground_truth` field
- **WHEN** the harness loads the corpus
- **THEN** the harness aborts with an error identifying the malformed entry
- **AND** no claims are submitted to the system

### Requirement: Corpus entries are traceable to source

Each corpus entry SHALL include a `politifact_url` linking directly to the published PolitiFact ruling and a `captured_date` recording when the entry was assembled. This enables manual re-verification if PolitiFact updates a verdict.

#### Scenario: All corpus entries have valid PolitiFact URLs

- **WHEN** the `politifact_url` field of each corpus entry is inspected
- **THEN** all 50 values are non-empty strings beginning with "https://www.politifact.com/"

#### Scenario: All corpus entries have capture dates in the past

- **WHEN** the `captured_date` field of each corpus entry is inspected
- **THEN** all 50 values parse as valid YYYY-MM-DD dates
- **AND** all 50 dates are on or before the current date
