# Agent: Evidence

## Overview

| Field | Value |
|-------|-------|
| **Agent ID** | `evidence` |
| **Pipeline Phase** | Phase 2 — Parallel Fan-Out |
| **Pipeline Node** | `pipeline/nodes/evidence.py` |
| **Agent Module** | `agents/evidence/` |
| **Execution Model** | LLM-driven ReAct loop (agent selects tools) |
| **Consolidates** | `claimreview-matcher`, `domain-evidence` |

The evidence agent gathers external evidence for the claim. It searches for existing fact-checks via the Google Fact Check Tools API, routes to domain-specific authoritative sources (CDC, SEC, WHO, etc.) based on the claim's domain, fetches source content, and scores how well the evidence aligns with or contradicts the claim.

## Capabilities

1. **Fact-check lookup** — Searches Google Fact Check Tools API for existing ClaimReview entries matching the claim
2. **Domain source routing** — Maps claim domain to authoritative sources using `routes.json` lookup table
3. **Content retrieval** — Fetches text content from up to 3 domain sources
4. **Evidence scoring** — Computes alignment (supports/contradicts/partial/absent) and confidence scores

## Tools

| Tool | Description |
|------|-------------|
| `search_factchecks()` | Google Fact Check Tools API query for existing fact-checks |
| `lookup_domain_sources()` | Routes claim domain → authoritative source URLs via `routes.json` |
| `fetch_source_content()` | HTTP retrieval of source document text (up to 3 sources) |
| `score_evidence()` | Computes alignment and confidence from retrieved evidence |

## Input

| Field | Type | Description |
|-------|------|-------------|
| `normalized_claim` | `str` | Normalized claim text from intake |
| `claim_domain` | `str` | Domain classification (HEALTHCARE, ECONOMICS, etc.) |
| `entities` | `dict` | Extracted entities (persons, organizations) |

Typed model: `EvidenceInput` in `agents/evidence/models.py`

## Output

| Field | Type | Description |
|-------|------|-------------|
| `claimreview_matches` | `list` | Matched ClaimReview entries with verdicts and scores |
| `domain_sources` | `list` | Authoritative sources consulted with alignment results |
| `evidence_confidence` | `float` | Overall evidence confidence score |

Typed model: `EvidenceOutput` in `agents/evidence/models.py`

## Observation Codes

| Code | Value Type | Description |
|------|-----------|-------------|
| `CLAIMREVIEW_MATCH` | CWE | Whether a ClaimReview match was found (TRUE/FALSE) |
| `CLAIMREVIEW_VERDICT` | CWE | Verdict from matched ClaimReview (e.g., FALSE^False^POLITIFACT) |
| `CLAIMREVIEW_SOURCE` | ST | Fact-checking organization name |
| `CLAIMREVIEW_URL` | ST | URL of the matched fact-check article |
| `CLAIMREVIEW_MATCH_SCORE` | NM | Semantic similarity score (0.0–1.0, flag < 0.75) |
| `DOMAIN_SOURCE_NAME` | ST | Authoritative source name (e.g., CDC, SEC) |
| `DOMAIN_SOURCE_URL` | ST | Authoritative source document URL |
| `DOMAIN_EVIDENCE_ALIGNMENT` | CWE | SUPPORTS / CONTRADICTS / PARTIAL / ABSENT |
| `DOMAIN_CONFIDENCE` | NM | Evidence confidence (0.0–1.0, penalized for indirect/dated sources) |

## External Dependencies

| Dependency | Purpose | Required Env Var |
|-----------|---------|-----------------|
| Google Fact Check Tools API | ClaimReview lookup | `GOOGLE_FACTCHECK_API_KEY` |
| Domain source endpoints | CDC, SEC, WHO, PubMed, etc. | None (public APIs) |

## Domain Source Routes

Source routing is defined in `agents/evidence/routes.json`:

| Domain | Sources |
|--------|---------|
| HEALTHCARE | CDC, WHO, NIH PubMed |
| ECONOMICS | SEC EDGAR, FRED, BLS |
| POLICY | Congress.gov, GovInfo, Federal Register |
| SCIENCE | PubMed, arXiv, NIH |
| ELECTION | FEC, Ballotpedia |
| CRIME | FBI UCR, BJS, DOJ |
| OTHER | Google (.gov/.edu filtered) |

## Invariants

- **INV-1**: ClaimReview matches with semantic similarity below 0.75 are flagged as uncertain.
- **INV-2**: At most 3 domain sources are fetched per run to bound latency.
- **INV-3**: The agent uses a ReAct loop — the LLM decides tool invocation order, not fixed sequencing.
- **INV-4**: If no ClaimReview match is found, the agent still proceeds with domain evidence gathering.
