## ADDED Requirements

### Requirement: Domain routing based on CLAIM_DOMAIN

The `domain-evidence` agent SHALL read the CLAIM_DOMAIN observation from the upstream Redis stream before executing. Based on the CLAIM_DOMAIN value, the agent SHALL select an ordered list of authoritative source URL templates from its `routes.json` fixture. The agent SHALL attempt sources in priority order until one returns HTTP 200 with content that appears relevant (relevance heuristic: at least one ENTITY_PERSON, ENTITY_ORG, or a keyword from CLAIM_NORMALIZED appears in the page title or first heading). The agent runs as a Temporal activity worker in the shared agent-service container (ADR-0016).

Domain routing table (from `routes.json`):
- `HEALTHCARE`: CDC, WHO, NIH PubMed
- `ECONOMICS`: SEC EDGAR, FRED (St. Louis Fed), BLS
- `POLICY`: Congress.gov, GovInfo, Federal Register
- `SCIENCE`: PubMed, arXiv, NIH
- `ELECTION`: FEC, Ballotpedia, official state SOS sites
- `CRIME`: FBI UCR, BJS, DOJ
- `OTHER`: fallback to Google Search restricted to `.gov` and `.edu` domains

#### Scenario: HEALTHCARE domain routes to CDC first

- **GIVEN** CLAIM_DOMAIN = "HEALTHCARE"
- **AND** CLAIM_NORMALIZED = "covid vaccines reduced hospitalizations by 90%"
- **WHEN** the domain-evidence activity executes
- **THEN** it first queries the CDC search endpoint with derived query terms
- **AND** if CDC returns relevant content, selects it as the primary source

#### Scenario: Fallback when primary source returns no relevant content

- **GIVEN** CLAIM_DOMAIN = "ECONOMICS"
- **AND** the SEC EDGAR search returns 0 results for the query
- **WHEN** the agent processes the response
- **THEN** it falls back to FRED (second in priority)
- **AND** if FRED returns relevant content, that becomes the primary source

#### Scenario: OTHER domain uses restricted web search

- **GIVEN** CLAIM_DOMAIN = "OTHER"
- **WHEN** the agent executes
- **THEN** it queries Google Search with `site:gov OR site:edu` restriction
- **AND** selects the first result that contains claim keywords

---

### Requirement: Query term derivation from claim and entities

The agent SHALL derive a search query from: the CLAIM_NORMALIZED text (first 80 characters, stop words removed) supplemented by ENTITY_PERSON, ENTITY_ORG, and ENTITY_DATE values. Person and organization entity names are prepended to the query for specificity. The ENTITY_STATISTIC value (if present) is appended verbatim to preserve numeric precision.

#### Scenario: Query includes entity context

- **GIVEN** CLAIM_NORMALIZED = "the fda approved the pfizer vaccine for children under 5"
- **AND** ENTITY_PERSON = [] (no persons)
- **AND** ENTITY_ORG = ["FDA", "Pfizer"]
- **AND** ENTITY_DATE = "20220617"
- **WHEN** the query is derived
- **THEN** the search query = "FDA Pfizer fda approved pfizer vaccine children under 5 2022-06-17"

---

### Requirement: Alignment scoring

The agent SHALL classify how well the retrieved primary source content aligns with the claim using a keyword overlap heuristic:
- Count claim keywords present in the retrieved document content (title + first 500 chars of body)
- Count negation patterns co-occurring with claim keywords (e.g. "not", "no evidence", "false", "debunked")
- Apply the following mapping:

```
overlap_ratio = matching_keywords / total_claim_keywords
has_negation = any negation pattern co-occurs with claim keyword

if overlap_ratio >= 0.6 and not has_negation -> SUPPORTS^Supports Claim^FCK
if overlap_ratio >= 0.6 and has_negation     -> CONTRADICTS^Contradicts Claim^FCK
if 0.3 <= overlap_ratio < 0.6               -> PARTIAL^Partially Supports^FCK
if overlap_ratio < 0.3 or no source found  -> ABSENT^No Evidence Found^FCK
```

#### Scenario: High keyword overlap with no negation -> SUPPORTS

- **GIVEN** the claim has 8 keywords
- **AND** the primary source document contains 7 of those keywords with no negation patterns
- **WHEN** alignment scoring runs
- **THEN** DOMAIN_EVIDENCE_ALIGNMENT = "SUPPORTS^Supports Claim^FCK"

#### Scenario: High overlap with negation -> CONTRADICTS

- **GIVEN** overlap_ratio = 0.75
- **AND** the phrase "no evidence" co-occurs with a claim keyword
- **THEN** DOMAIN_EVIDENCE_ALIGNMENT = "CONTRADICTS^Contradicts Claim^FCK"

#### Scenario: No relevant source found

- **GIVEN** all sources in the routing table fail the relevance heuristic
- **THEN** DOMAIN_EVIDENCE_ALIGNMENT = "ABSENT^No Evidence Found^FCK"

---

### Requirement: Confidence scoring with penalty factors

The agent SHALL publish DOMAIN_CONFIDENCE (NM: 0.0-1.0) reflecting confidence in the alignment finding. Base confidence starts at 1.0 and is penalized as follows:
- Source is a fallback (not the first in the routing priority list): -0.10 per fallback step
- Source document is older than 2 years (based on publication date): -0.15
- Source is indirect (e.g. a news article referencing an original report, not the report itself): -0.20
- Alignment is PARTIAL: -0.10
- Alignment is ABSENT: confidence = 0.0 (floor, regardless of source quality)

Minimum non-zero confidence: 0.10

#### Scenario: Primary source, recent, direct -> confidence near 1.0

- **GIVEN** DOMAIN_EVIDENCE_ALIGNMENT = "SUPPORTS"
- **AND** source is CDC (first priority), document published 3 months ago, direct primary source
- **THEN** DOMAIN_CONFIDENCE = 1.0 (no penalties applied)

#### Scenario: Fallback source with PARTIAL alignment

- **GIVEN** agent fell back 2 steps to NIH
- **AND** alignment = PARTIAL
- **WHEN** confidence is computed
- **THEN** DOMAIN_CONFIDENCE = 1.0 - 0.10 - 0.10 - 0.10 = 0.70

#### Scenario: Absent alignment sets confidence to 0.0

- **GIVEN** DOMAIN_EVIDENCE_ALIGNMENT = "ABSENT"
- **THEN** DOMAIN_CONFIDENCE = 0.0

---

### Requirement: Four-observation output with epistemic status

The agent SHALL publish four observations in sequence:
1. DOMAIN_SOURCE_NAME (ST: authoritative source name, e.g. "CDC"), status = F
2. DOMAIN_SOURCE_URL (ST: URL of the specific document), status = F
3. DOMAIN_EVIDENCE_ALIGNMENT (CWE: SUPPORTS|CONTRADICTS|PARTIAL|ABSENT), status = F
4. DOMAIN_CONFIDENCE (NM: 0.0-1.0), status = F

When DOMAIN_EVIDENCE_ALIGNMENT = ABSENT (no source found), DOMAIN_SOURCE_NAME and DOMAIN_SOURCE_URL SHALL still be published with the value "N/A" to maintain a consistent 4-observation output that the synthesizer can depend on.

All observations SHALL be constructed via the `publish_observation` tool (ADR-0004).

#### Scenario: Full 4-observation output in all cases

- **GIVEN** any outcome (SUPPORTS, CONTRADICTS, PARTIAL, or ABSENT)
- **WHEN** observations are published
- **THEN** exactly 4 observations are emitted with seq = [1, 2, 3, 4]
- **AND** STOP.observationCount = 4

#### Scenario: ABSENT case uses N/A placeholders

- **GIVEN** no relevant source was found
- **THEN** DOMAIN_SOURCE_NAME = "N/A"
- **AND** DOMAIN_SOURCE_URL = "N/A"
- **AND** DOMAIN_EVIDENCE_ALIGNMENT = "ABSENT^No Evidence Found^FCK"
- **AND** DOMAIN_CONFIDENCE = "0.0"
- **AND** STOP.finalStatus = F (ABSENT is a valid finding, not a failure)

---

### Requirement: Progress event publishing

The agent SHALL publish progress events to `progress:{runId}` at key milestones: activity start ("Consulting domain sources..."), source found ("Found evidence from {source_name}"), and completion. These events are relayed to the frontend via SSE (ADR-0018).

#### Scenario: Progress events during successful lookup

- **GIVEN** the agent finds relevant content from CDC
- **WHEN** the agent executes
- **THEN** progress events include "Consulting domain sources..." and "Found evidence from CDC"

---

### Requirement: HTTP fetch resilience (NFR-012)

All HTTP fetches SHALL use `httpx` with a 10-second timeout per request. HTTP 3xx redirects SHALL be followed automatically (up to 5 redirects). HTTP 4xx responses on a source shall cause the agent to skip to the next source in the routing list. HTTP 5xx responses SHALL be retried once after 1 second; if the retry fails, the source is skipped.

#### Scenario: 404 on primary source triggers fallback

- **GIVEN** CLAIM_DOMAIN = "HEALTHCARE"
- **AND** the CDC endpoint returns HTTP 404
- **WHEN** the agent processes this response
- **THEN** it skips to the WHO endpoint (second priority)
- **AND** no error observation is published for the 404 (silently skipped)

#### Scenario: All sources return HTTP errors

- **GIVEN** all sources in the routing table for the claim's domain return HTTP 5xx
- **WHEN** the agent exhausts all options
- **THEN** DOMAIN_EVIDENCE_ALIGNMENT = "ABSENT^No Evidence Found^FCK"
- **AND** DOMAIN_CONFIDENCE = "0.0"
- **AND** STOP.finalStatus = F (not X -- exhausted search is a valid outcome)

---

### Requirement: Agent latency <= 20 seconds (NFR-002 budget)

The agent SHALL complete within 20 seconds under normal conditions. A 30-second internal timeout SHALL be enforced via `asyncio.wait_for`. The Temporal activity timeout is 45 seconds. Per-source HTTP timeouts (10 seconds each) plus up to 2 source attempts gives a maximum HTTP time of 20 seconds -- within the soft target.

#### Scenario: Completes within budget on first-source hit

- **GIVEN** the first-priority source returns relevant content within 5 seconds
- **WHEN** alignment scoring and observation publishing complete
- **THEN** total wall-clock from START to STOP <= 20 seconds

#### Scenario: Hard timeout enforced

- **GIVEN** all HTTP fetches collectively exceed 30 seconds
- **THEN** the agent cancels pending fetches, sets alignment = ABSENT, confidence = 0.0, and emits STOP with finalStatus = X
