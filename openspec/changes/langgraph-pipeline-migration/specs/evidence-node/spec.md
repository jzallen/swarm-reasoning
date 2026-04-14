## ADDED Requirements

### Requirement: Evidence node combines fact-check lookup and domain-specific evidence
The system SHALL implement an `evidence_node` async function in `pipeline/nodes/evidence.py` that accepts PipelineState and RunnableConfig and returns a dict with keys: claimreview_matches, domain_sources, evidence_confidence. The node SHALL use 4 tools: search_factchecks (Google Fact Check Tools API), derive_evidence_query, fetch_domain_source (CDC, SEC, WHO, PubMed, etc.), score_evidence.

#### Scenario: Evidence found via ClaimReview
- **WHEN** evidence_node processes a claim that has existing fact-checks
- **THEN** claimreview_matches contains at least one match with publisher, url, and rating fields

#### Scenario: Evidence from domain sources
- **WHEN** evidence_node processes a health claim
- **THEN** domain_sources contains entries with source, url, and relevance_score from domain-specific APIs

#### Scenario: Graceful degradation when APIs unavailable
- **WHEN** the Google Fact Check API returns an error
- **THEN** evidence_node records the error in PipelineState.errors, sets claimreview_matches to empty list, and continues processing with domain sources only

### Requirement: Evidence node reads input from PipelineState
The system SHALL read normalized_claim, claim_domain, and entities from PipelineState. The node SHALL NOT read from Redis Streams for upstream data.

#### Scenario: Evidence node uses intake output from state
- **WHEN** evidence_node executes after intake_node
- **THEN** it reads normalized_claim and entities from PipelineState, not from a Redis stream
