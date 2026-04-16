# Capability Spec: claim-intake

## Summary

The `claim-intake` capability is a LangChain tool (`ingest_claim`) invoked within the ingestion-agent's Temporal activity execution. It receives a raw claim submission, performs structural validation, extracts and normalizes metadata, and publishes `CLAIM_TEXT`, `CLAIM_SOURCE_URL`, and `CLAIM_SOURCE_DATE` observations to the run's Redis Stream. It manages the stream open: publishing `START` before the first observation and `STOP` on rejection (or leaving the stream open for `classify_domain` on success).

## Tool Signature

```python
async def ingest_claim(
    run_id: str,           # run identifier, format: {claim_slug}-run-{seq}
    claim_text: str,       # raw claim text to fact-check
    source_url: str | None = None,   # URL of the source document
    source_date: str | None = None,  # publication date, any parseable format
    *,
    stream: ReasoningStream,         # injected dependency
    redis_client: redis.asyncio.Redis,  # for dedup check
) -> IngestionResult
```

```python
class IngestionResult(BaseModel):
    accepted: bool
    run_id: str
    rejection_reason: str | None = None   # populated when accepted=False
    normalized_date: str | None = None    # YYYYMMDD format, populated when accepted=True
```

## Validation Rules

Rules are applied in order. Failure at any step causes immediate rejection.

| # | Rule | Condition | Rejection Reason |
|---|---|---|---|
| 1 | Text present | `claim_text` is not empty after strip | `CLAIM_TEXT_EMPTY` |
| 2 | Text minimum length | `len(claim_text.strip()) >= 5` | `CLAIM_TEXT_TOO_SHORT` |
| 3 | Text maximum length | `len(claim_text.strip()) <= 2000` | `CLAIM_TEXT_TOO_LONG` |
| 4 | URL format | If `source_url` present: matches `^https?://[^\s]+\.[^\s]{2,}$` | `SOURCE_URL_INVALID_FORMAT` |
| 5 | Date parseable | If `source_date` present: parseable by `dateutil.parser.parse` | `SOURCE_DATE_UNPARSEABLE` |
| 6 | Duplicate detection | `SETNX reasoning:dedup:{run_id}:{sha256(claim_text.strip())}` returns 1 (new key) | `DUPLICATE_CLAIM_IN_RUN` |

Duplicate detection key TTL: 86400 seconds (24 hours).

## Stream Lifecycle

On call to `ingest_claim`:

1. Publish `START` message with `phase="ingestion"` and `agent="ingestion-agent"`
2. Publish progress event to `progress:{runId}`: `"Validating claim submission..."`
3. Run validation (rules 1-6 above)
4. **If validation fails:**
   - Publish one `OBS` for `CLAIM_TEXT` with the submitted text and `status="X"`, `note=rejection_reason`
   - Publish `STOP` with `finalStatus="X"`, `observationCount=1`
   - Publish progress event: `"Claim rejected: {rejection_reason}"`
   - Return `IngestionResult(accepted=False, run_id=run_id, rejection_reason=...)`
5. **If validation passes:**
   - Publish `OBS` for `CLAIM_TEXT`, `status="F"`, `valueType="ST"`
   - Publish `OBS` for `CLAIM_SOURCE_URL`, `status="F"`, `valueType="ST"` (value = empty string `""` if not supplied)
   - Publish `OBS` for `CLAIM_SOURCE_DATE`, `status="F"`, `valueType="ST"`, value = normalized YYYYMMDD (empty string if not supplied)
   - Publish progress event: `"Claim accepted, classifying domain..."`
   - Leave stream open (caller `classify_domain` will close it)
   - Return `IngestionResult(accepted=True, run_id=run_id, normalized_date=...)`

Note: `STOP` is NOT published by `ingest_claim` on success -- the stream remains open for `classify_domain` to publish `CLAIM_DOMAIN` before closing. The `classify_domain` tool is responsible for the `STOP` message on the success path.

## Observation Details

| OBX Code | Value | valueType | status | units | referenceRange | note |
|---|---|---|---|---|---|---|
| `CLAIM_TEXT` | Stripped claim text | `ST` | `F` (accept) or `X` (reject) | null | null | null (accept) or rejection reason (reject) |
| `CLAIM_SOURCE_URL` | Source URL or `""` | `ST` | `F` | null | null | null |
| `CLAIM_SOURCE_DATE` | YYYYMMDD or `""` | `ST` | `F` | null | null | null |

The `method` field on all three observations: `"ingest_claim"`.

## Date Normalization

`source_date` is parsed with `dateutil.parser.parse` (lenient). The parsed date is serialized as `datetime.strftime("%Y%m%d")`. If parsing fails, rule 5 rejects the submission before any observation is published.

Examples:
- `"April 6, 2026"` -> `"20260406"`
- `"2026-04-06"` -> `"20260406"`
- `"04/06/26"` -> `"20260406"`
- `"not a date"` -> rejected with `SOURCE_DATE_UNPARSEABLE`

## Error Handling

| Error | Behavior |
|---|---|
| Redis connection failure during START | Raise `StreamPublishError`; no observations written; no STOP published; Temporal activity retries |
| Redis connection failure mid-stream | Raise `StreamPublishError`; stream is left in an open/incomplete state; Temporal workflow detects missing STOP via activity failure |
| `StreamNotOpenError` (stream already has a START for this run+agent) | Raise; do not publish duplicate START |

## Gherkin Acceptance Criteria

```gherkin
Feature: Claim Intake

  Scenario: Valid claim with full metadata is accepted
    Given a claim "The unemployment rate hit a 50-year low in 2019"
    And source_url "https://bls.gov/news.release/empsit.htm"
    And source_date "January 10, 2020"
    When ingest_claim is called with run_id "test-run-001"
    Then the result has accepted=True
    And the stream "reasoning:test-run-001:ingestion-agent" contains a START message
    And the stream contains OBS for CLAIM_TEXT with status F
    And the stream contains OBS for CLAIM_SOURCE_URL with status F
    And the stream contains OBS for CLAIM_SOURCE_DATE with value "20200110" and status F
    And the stream does NOT contain a STOP message
    And the progress stream contains "Claim accepted, classifying domain..."

  Scenario: Claim text too short is rejected
    Given a claim "Yes"
    When ingest_claim is called with run_id "test-run-002"
    Then the result has accepted=False and rejection_reason CLAIM_TEXT_TOO_SHORT
    And the stream contains OBS for CLAIM_TEXT with status X
    And the stream contains a STOP message with finalStatus X
    And the progress stream contains "Claim rejected: CLAIM_TEXT_TOO_SHORT"

  Scenario: Duplicate claim in same run is rejected
    Given a prior accepted call for claim "The sky is blue" in run "test-run-003"
    When ingest_claim is called again with the same claim text and run_id "test-run-003"
    Then the result has accepted=False and rejection_reason DUPLICATE_CLAIM_IN_RUN

  Scenario: Invalid source URL format is rejected
    Given a claim "GDP grew 3% in Q3" with source_url "not-a-url"
    When ingest_claim is called
    Then the result has accepted=False and rejection_reason SOURCE_URL_INVALID_FORMAT

  Scenario: Unparseable source date is rejected
    Given a claim "Taxes were raised last year" with source_date "yesterday-ish"
    When ingest_claim is called
    Then the result has accepted=False and rejection_reason SOURCE_DATE_UNPARSEABLE
```
