## ADDED Requirements

### Requirement: Three independent coverage agents as Temporal activities

The system SHALL implement three coverage agents -- `coverage-left`, `coverage-center`, `coverage-right` -- as Temporal activity workers in the shared agent-service container (ADR-0016). Each agent is an instance of a shared `CoverageActivity` class parameterized by a `spectrum` value ("left" | "center" | "right"). Each agent maintains a static source list (`sources.json`) containing NewsAPI source IDs for its spectrum segment. No per-agent containers or MCP servers are required.

Source list examples (not exhaustive):
- **left**: `huffington-post`, `msnbc`, `the-nation`, `mother-jones`, `the-intercept`
- **center**: `reuters`, `associated-press`, `the-hill`, `axios`, `bloomberg`
- **right**: `fox-news`, `breitbart-news`, `the-blaze`, `daily-caller`, `washington-times`

Each agent writes to its own stream key: `reasoning:{runId}:coverage-{spectrum}`. No agent reads from another coverage agent's stream.

#### Scenario: Three agents write to independent streams

- **GIVEN** the orchestrator Temporal workflow dispatches all three coverage activities for run "run-042"
- **WHEN** all three execute concurrently as Temporal activities
- **THEN** streams `reasoning:run-042:coverage-left`, `reasoning:run-042:coverage-center`, and `reasoning:run-042:coverage-right` each contain one START, 4 OBX, and one STOP message
- **AND** no agent reads from another's stream during execution

---

### Requirement: NewsAPI query using claim-derived search terms

Each coverage agent SHALL query the NewsAPI `/v2/everything` endpoint using:
- `q`: derived from CLAIM_NORMALIZED (first 100 characters, removing stop words)
- `sources`: the agent's spectrum source list (comma-joined, max 20 sources per NewsAPI limit)
- `sortBy`: `relevancy`
- `pageSize`: 10
- `language`: `en`

The `NEWSAPI_KEY` environment variable SHALL be used for authentication.

#### Scenario: Query built from normalized claim

- **GIVEN** CLAIM_NORMALIZED = "the unemployment rate fell to 3.4% in january 2023"
- **WHEN** coverage-left queries NewsAPI
- **THEN** `q` = "unemployment rate fell 3.4% january 2023" (stop words removed)
- **AND** `sources` = the left-spectrum source list from `sources.json`

#### Scenario: Query truncated to 100 characters

- **GIVEN** CLAIM_NORMALIZED is 250 characters long
- **WHEN** the search term is derived
- **THEN** `q` is truncated to 100 characters at a word boundary

---

### Requirement: Framing detection from headline sentiment

Each agent SHALL classify the dominant framing of returned articles using VADER SentimentIntensityAnalyzer (no external API call). The framing SHALL be derived from the average compound sentiment score across the top 5 articles (or all articles if fewer than 5 returned):

- compound >= 0.05 -> SUPPORTIVE^Supportive^FCK
- compound <= -0.05 -> CRITICAL^Critical^FCK
- -0.05 < compound < 0.05 -> NEUTRAL^Neutral^FCK
- 0 articles returned -> ABSENT^Not Covered^FCK

#### Scenario: Left spectrum frames claim supportively

- **GIVEN** coverage-left retrieves 5 articles with average VADER compound = 0.32
- **WHEN** framing detection runs
- **THEN** COVERAGE_FRAMING = "SUPPORTIVE^Supportive^FCK"

#### Scenario: No articles returned

- **GIVEN** NewsAPI returns 0 articles for this spectrum's sources
- **WHEN** the agent processes results
- **THEN** COVERAGE_ARTICLE_COUNT = "0"
- **AND** COVERAGE_FRAMING = "ABSENT^Not Covered^FCK"
- **AND** COVERAGE_TOP_SOURCE and COVERAGE_TOP_SOURCE_URL are NOT published

---

### Requirement: Top source selection by credibility rank

Each agent's `sources.json` SHALL include a credibility rank (integer 1-100) for each source. When multiple articles are returned, the agent SHALL select the article from the highest-ranked source as the top source. If multiple articles share the top-ranked source, the most recently published article SHALL be selected.

#### Scenario: Top source is the highest-ranked returning source

- **GIVEN** coverage-center returns articles from reuters (rank 95), axios (rank 80), and the-hill (rank 72)
- **WHEN** the agent selects the top source
- **THEN** COVERAGE_TOP_SOURCE = "Reuters"
- **AND** COVERAGE_TOP_SOURCE_URL = the URL of the Reuters article

#### Scenario: Single article returned

- **GIVEN** NewsAPI returns exactly one article from bloomberg (rank 90)
- **THEN** COVERAGE_TOP_SOURCE = "Bloomberg"
- **AND** COVERAGE_TOP_SOURCE_URL = that article's URL

---

### Requirement: Four-observation output with epistemic status

Each coverage agent SHALL publish four observations in sequence:
1. COVERAGE_ARTICLE_COUNT (NM: integer >= 0), status = F
2. COVERAGE_FRAMING (CWE: SUPPORTIVE|CRITICAL|NEUTRAL|ABSENT), status = F
3. COVERAGE_TOP_SOURCE (ST: source name), status = F -- OMITTED if article count = 0
4. COVERAGE_TOP_SOURCE_URL (ST: article URL), status = F -- OMITTED if article count = 0

When article count = 0, the agent SHALL publish 2 observations (COVERAGE_ARTICLE_COUNT + COVERAGE_FRAMING=ABSENT) and emit STOP with observationCount = 2, finalStatus = F (not X -- zero coverage is a valid result, not a failure).

All observations SHALL be constructed via the `publish_observation` tool (ADR-0004).

#### Scenario: Full 4-observation output when articles found

- **GIVEN** coverage-right retrieves 7 articles
- **WHEN** observations are published
- **THEN** seq = [1, 2, 3, 4] with codes [COVERAGE_ARTICLE_COUNT, COVERAGE_FRAMING, COVERAGE_TOP_SOURCE, COVERAGE_TOP_SOURCE_URL]
- **AND** all have status = F
- **AND** STOP.observationCount = 4

#### Scenario: 2-observation output when no articles found

- **GIVEN** coverage-center retrieves 0 articles
- **THEN** only COVERAGE_ARTICLE_COUNT and COVERAGE_FRAMING are published
- **AND** STOP.finalStatus = F (not X)
- **AND** STOP.observationCount = 2

---

### Requirement: Progress event publishing

Each coverage agent SHALL publish progress events to `progress:{runId}` at key milestones: activity start ("Searching {spectrum} media sources..."), results found ("Found {n} articles from {spectrum} sources"), and completion. These events are relayed to the frontend via SSE (ADR-0018).

#### Scenario: Progress events during analysis

- **GIVEN** coverage-left finds 8 articles
- **WHEN** the agent executes
- **THEN** progress events include "Searching left media sources..." and "Found 8 articles from left sources"

---

### Requirement: NewsAPI failure handling

If NewsAPI returns HTTP 4xx or 5xx, or if `NEWSAPI_KEY` is not set, the agent SHALL publish COVERAGE_ARTICLE_COUNT = "0" with status = X and COVERAGE_FRAMING = "ABSENT^Not Covered^FCK" with status = X, then emit STOP with finalStatus = X.

HTTP 429 (rate limit) SHALL be retried once after 1 second. If the retry fails, graceful failure proceeds.

#### Scenario: NewsAPI returns HTTP 401 (invalid key)

- **GIVEN** NEWSAPI_KEY is invalid
- **WHEN** the agent queries NewsAPI
- **THEN** COVERAGE_ARTICLE_COUNT is published with status = X and note = "API error: HTTP 401"
- **AND** COVERAGE_FRAMING is published with status = X and value = "ABSENT^Not Covered^FCK"
- **AND** STOP.finalStatus = X

---

### Requirement: Agent latency <= 20 seconds (NFR-002 budget)

Each coverage agent SHALL complete within 20 seconds (30-second internal timeout, 45-second Temporal activity timeout). Framing detection (VADER) is local and SHALL add <= 1 second. The NewsAPI call is expected to complete within 5 seconds.

#### Scenario: Execution within budget

- **GIVEN** NewsAPI responds within 5 seconds
- **WHEN** framing detection and observation publishing complete
- **THEN** total wall-clock from START to STOP <= 20 seconds

#### Scenario: Timeout enforced

- **GIVEN** the NewsAPI call takes > 30 seconds
- **THEN** the agent cancels the request, publishes X-status observations, and emits STOP with finalStatus = X
