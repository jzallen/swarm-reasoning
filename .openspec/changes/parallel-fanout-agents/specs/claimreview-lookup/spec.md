## ADDED Requirements

### Requirement: ClaimReview API search using normalized claim and entities

The `claimreview-matcher` agent SHALL query the Google Fact Check Tools API (`https://factchecktools.googleapis.com/v1alpha1/claims:search`) using the normalized claim text (CLAIM_NORMALIZED) read from the upstream Redis stream. If ENTITY_PERSON or ENTITY_ORG observations are present, the agent SHALL include the most prominent entity name in the query to improve precision. The API call SHALL use the `GOOGLE_FACTCHECK_API_KEY` environment variable for authentication. The agent runs as a Temporal activity worker in the shared agent-service container (ADR-0016).

#### Scenario: Successful API query with claim text

- **GIVEN** CLAIM_NORMALIZED = "the unemployment rate fell to 3.4% in January 2023"
- **AND** ENTITY_STATISTIC = "3.4%", ENTITY_DATE = "20230101"
- **WHEN** the claimreview-matcher activity executes
- **THEN** it queries the API with query = "unemployment rate 3.4% January 2023"
- **AND** publishes a START message to `reasoning:{runId}:claimreview-matcher`

#### Scenario: Query falls back to normalized claim when no entities present

- **GIVEN** CLAIM_NORMALIZED = "vaccines cause autism"
- **AND** no ENTITY_* observations are in the stream
- **WHEN** the activity executes
- **THEN** it queries the API with query = "vaccines cause autism"

---

### Requirement: Semantic match scoring via cosine similarity

The agent SHALL compute a match score for each ClaimReview result returned by the API using cosine similarity over TF-IDF vectors of the submitted CLAIM_NORMALIZED text vs. the `claimReviewed` field from the API response. The highest-scoring result SHALL be selected. If multiple results share the top score (tie-break: most recent `claimDate`), the most recent SHALL be used.

Match score thresholds:
- score >= 0.75 -> strong match (CLAIMREVIEW_MATCH = TRUE)
- 0.50 <= score < 0.75 -> uncertain match (CLAIMREVIEW_MATCH = TRUE, synthesizer applies its own threshold)
- score < 0.50 -> no match (CLAIMREVIEW_MATCH = FALSE, remaining codes omitted)

#### Scenario: High-confidence match selected

- **GIVEN** the API returns 3 ClaimReview results
- **AND** cosine similarities are [0.91, 0.62, 0.45]
- **WHEN** match scoring completes
- **THEN** the result with score 0.91 is selected
- **AND** CLAIMREVIEW_MATCH_SCORE observation has value "0.91"
- **AND** CLAIMREVIEW_MATCH has value "TRUE^Match Found^FCK"

#### Scenario: Below-threshold result treated as no match

- **GIVEN** the API returns 2 results with similarities [0.41, 0.38]
- **WHEN** match scoring completes
- **THEN** CLAIMREVIEW_MATCH has value "FALSE^No Match^FCK"
- **AND** CLAIMREVIEW_MATCH_SCORE has value "0.0"
- **AND** CLAIMREVIEW_VERDICT, CLAIMREVIEW_SOURCE, CLAIMREVIEW_URL are NOT published

---

### Requirement: Five-observation output with epistemic status

On a successful match (score >= 0.50), the agent SHALL publish five observations in sequence:
1. CLAIMREVIEW_MATCH (CWE: TRUE^Match Found^FCK | FALSE^No Match^FCK), status = F
2. CLAIMREVIEW_VERDICT (CWE: original reviewer rating, e.g. FALSE^False^POLITIFACT), status = F
3. CLAIMREVIEW_SOURCE (ST: organization name, e.g. "PolitiFact"), status = F
4. CLAIMREVIEW_URL (ST: article URL), status = F
5. CLAIMREVIEW_MATCH_SCORE (NM: 0.0-1.0), status = F

On no match, the agent SHALL publish:
1. CLAIMREVIEW_MATCH (CWE: FALSE^No Match^FCK), status = F
2. CLAIMREVIEW_MATCH_SCORE (NM: 0.0), status = F

All observations SHALL be constructed via the `publish_observation` tool (ADR-0004). The agent SHALL never construct raw JSON observations directly.

#### Scenario: Matched observations are published in seq order

- **GIVEN** a match with score 0.88 is found
- **WHEN** the agent publishes observations
- **THEN** seq values are [1, 2, 3, 4, 5] in the stream
- **AND** all observations have status = F
- **AND** CLAIMREVIEW_VERDICT value follows format `{rating}^{display}^{system}` (e.g. "FALSE^False^POLITIFACT")

#### Scenario: STOP message follows last observation

- **WHEN** the agent has published all observations
- **THEN** it publishes a STOP message with finalStatus = F and observationCount matching the number of OBX rows emitted

---

### Requirement: Progress event publishing

The agent SHALL publish progress events to `progress:{runId}` at key milestones: activity start ("Searching fact-check databases..."), match found ("Found matching fact-check from {source}"), no match ("No existing fact-check found"), and completion. These events are relayed to the frontend via SSE (ADR-0018).

#### Scenario: Progress events during successful match

- **GIVEN** the agent finds a matching fact-check from PolitiFact
- **WHEN** the agent executes
- **THEN** progress events include "Searching fact-check databases..." and "Found matching fact-check from PolitiFact"

---

### Requirement: Graceful handling of API failures and quota exhaustion

If the Google Fact Check Tools API returns HTTP 4xx or 5xx, or if the `GOOGLE_FACTCHECK_API_KEY` is missing, the agent SHALL publish CLAIMREVIEW_MATCH = FALSE (status = X, note = error description) and emit a STOP message with finalStatus = X. The agent SHALL NOT raise an unhandled exception or leave the run in a hung state. The Temporal activity SHALL return a `FanoutActivityResult` with status = "CANCELLED".

Rate limit responses (HTTP 429) SHALL be retried once after a 2-second delay. If the retry also fails, the agent proceeds to graceful failure.

#### Scenario: API returns HTTP 500

- **GIVEN** the Google API returns HTTP 500
- **WHEN** the agent executes
- **THEN** it publishes CLAIMREVIEW_MATCH with status = X and note = "API error: HTTP 500"
- **AND** emits STOP with finalStatus = X
- **AND** the Temporal activity returns `FanoutActivityResult(status="CANCELLED", reason="API error: HTTP 500")`

#### Scenario: API key missing

- **GIVEN** GOOGLE_FACTCHECK_API_KEY is not set
- **WHEN** the agent starts
- **THEN** it emits START, then CLAIMREVIEW_MATCH with status = X, then STOP with finalStatus = X
- **AND** logs a WARNING: "GOOGLE_FACTCHECK_API_KEY not configured"

---

### Requirement: Agent latency <= 20 seconds (NFR-002 budget)

The agent SHALL complete its full execution (START -> OBS -> STOP) within 20 seconds under normal conditions. A configurable internal timeout of 30 seconds SHALL be enforced via `asyncio.wait_for`. The Temporal activity timeout is 45 seconds. If the internal timeout is exceeded, the agent SHALL publish X-status observations and STOP.

#### Scenario: Execution completes within time budget

- **GIVEN** the Google API responds within 5 seconds
- **WHEN** the agent runs with a normal claim
- **THEN** total wall-clock time from START to STOP is <= 20 seconds

#### Scenario: Timeout enforced

- **GIVEN** the Google API takes > 30 seconds to respond
- **WHEN** the agent runs
- **THEN** the agent cancels the API call, publishes CLAIMREVIEW_MATCH with status = X and note = "Timeout after 30s"
- **AND** emits STOP with finalStatus = X
