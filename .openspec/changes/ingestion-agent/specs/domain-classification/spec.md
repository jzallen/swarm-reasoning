# Capability Spec: domain-classification

## Summary

The `domain-classification` capability is a LangChain tool (`classify_domain`) invoked within the ingestion-agent's Temporal activity execution. It assigns an incoming claim to one domain from a controlled vocabulary by calling Claude claude-sonnet-4-6. It publishes a `CLAIM_DOMAIN` observation and closes the stream with `finalStatus="F"`. This tool is always called after a successful `ingest_claim` call on the same `run_id`.

## Controlled Vocabulary

| Code | Label | Typical Subjects |
|---|---|---|
| `HEALTHCARE` | Healthcare | Medical treatments, drugs, public health statistics, hospital policy |
| `ECONOMICS` | Economics | GDP, unemployment, inflation, trade, wages, fiscal policy |
| `POLICY` | Policy | Legislation, government programs, regulatory decisions, executive orders |
| `SCIENCE` | Science | Climate, research findings, environmental statistics, technology |
| `ELECTION` | Election | Voting records, ballot counts, candidate statements, electoral rules |
| `CRIME` | Crime | Crime statistics, court outcomes, law enforcement actions |
| `OTHER` | Other | Claims that do not fit the above categories |

## Tool Signature

```python
async def classify_domain(
    run_id: str,        # must match a run with an open ingestion stream
    claim_text: str,    # the raw claim text to classify
    *,
    stream: ReasoningStream,         # injected dependency
    anthropic_client: AsyncAnthropic,  # injected dependency
) -> ClassificationResult
```

```python
class ClassificationResult(BaseModel):
    run_id: str
    domain: Literal["HEALTHCARE", "ECONOMICS", "POLICY", "SCIENCE", "ELECTION", "CRIME", "OTHER"]
    confidence: Literal["HIGH", "LOW"]   # HIGH = first-attempt success, LOW = fallback to OTHER
    attempt_count: int                   # 1 or 2
```

## Classification Algorithm

1. Build the classification prompt (see Prompt section below)
2. Call `anthropic.messages.create` with `model="claude-sonnet-4-6"`, `max_tokens=10`
3. Strip and uppercase the response text
4. If the response is exactly one of the seven vocabulary codes:
   - Publish `CLAIM_DOMAIN` with `status="P"` (preliminary, first attempt)
   - Publish `CLAIM_DOMAIN` again with `status="F"` (final, confirmed)
   - Set `confidence="HIGH"`, `attempt_count=1`
5. If the response is NOT in the vocabulary (attempt 1):
   - Retry once with the same prompt plus a clarification suffix
   - If retry returns a valid code:
     - Publish `CLAIM_DOMAIN` with `status="P"`
     - Publish `CLAIM_DOMAIN` with `status="F"` (confirmed)
     - Set `confidence="HIGH"`, `attempt_count=2`
   - If retry also fails:
     - Publish `CLAIM_DOMAIN` with value `"OTHER"` and `status="F"`, `note="LLM returned unrecognized value after 2 attempts; fallback applied"`
     - Set `confidence="LOW"`, `attempt_count=2`
6. Publish `STOP` with `finalStatus="F"` and `observationCount` = total OBS count for this stream (including observations from `ingest_claim`)
7. Publish progress event to `progress:{runId}`: `"Domain classified: {domain}"`

## Stream State Precondition

`classify_domain` requires that the stream `reasoning:{run_id}:ingestion-agent` exists and contains a `START` message with no `STOP`. If the stream does not exist or already has a `STOP`, raise `StreamStateError` before making any LLM call.

The tool reads the current stream to count existing observations so it can report the correct `observationCount` in the `STOP` message.

## Observation Details

### Preliminary CLAIM_DOMAIN (P status)

Published after the first successful LLM response, before the final confirmation:

| Field | Value |
|---|---|
| `code` | `CLAIM_DOMAIN` |
| `value` | The classified domain code (e.g., `"ECONOMICS"`) |
| `valueType` | `ST` |
| `status` | `P` |
| `method` | `"classify_domain"` |
| `note` | `null` |

### Final CLAIM_DOMAIN (F status)

Published immediately after the `P` observation:

| Field | Value |
|---|---|
| `code` | `CLAIM_DOMAIN` |
| `value` | Same domain code as the `P` observation |
| `valueType` | `ST` |
| `status` | `F` |
| `method` | `"classify_domain"` |
| `note` | `null` (or fallback note if `confidence=LOW`) |

The synthesizer resolves by selecting the most recent `F` observation for `CLAIM_DOMAIN` -- the `P` observation is informational only (ADR-003, Section 3.3 of observation-schema-spec.md).

## Classification Prompt

System prompt:
```
You are a domain classifier for a fact-checking system. Your task is to categorize the given claim into exactly one of the following domains:

HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER

Respond with exactly one word -- the domain code. Do not include punctuation, explanation, or any other text.
```

User message:
```
Claim: {claim_text}
```

Retry clarification suffix (appended to user message on second attempt):
```

Note: your previous response was not recognized. You must respond with exactly one of: HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER
```

## Anthropic API Configuration

| Parameter | Value |
|---|---|
| `model` | `claude-sonnet-4-6` |
| `max_tokens` | `10` |
| `temperature` | `0` (deterministic) |
| API key source | `ANTHROPIC_API_KEY` environment variable |

## Error Handling

| Error | Behavior |
|---|---|
| `anthropic.APIConnectionError` | Raise `ClassificationServiceError`; do not publish observations or STOP; stream remains open; Temporal activity retry handles it |
| `anthropic.RateLimitError` | Raise `ClassificationServiceError` (retryable); Temporal retries the activity |
| `anthropic.AuthenticationError` | Raise `ClassificationServiceError` (non-retryable); activity fails immediately |
| Two consecutive unrecognized responses | Publish `OTHER` with `status="F"` and fallback note; close stream with `finalStatus="F"` |
| `StreamStateError` (stream not open) | Raise before any LLM call |

The stream is NOT closed on transient Anthropic API errors -- Temporal's activity retry mechanism handles retries at the infrastructure level. The stream is only closed (with `STOP`) on success or on the two-strike fallback path.

## Gherkin Acceptance Criteria

```gherkin
Feature: Domain Classification

  Scenario: Claim classified correctly on first attempt
    Given an open ingestion stream for run "test-run-010" with CLAIM_TEXT "The Federal Reserve raised interest rates by 75 basis points"
    When classify_domain is called with run_id "test-run-010"
    Then Claude returns "ECONOMICS"
    And the stream contains OBS for CLAIM_DOMAIN with value "ECONOMICS" and status P
    And the stream contains OBS for CLAIM_DOMAIN with value "ECONOMICS" and status F
    And the stream contains a STOP message with finalStatus F
    And the ClassificationResult has domain="ECONOMICS", confidence="HIGH", attempt_count=1
    And the progress stream contains "Domain classified: ECONOMICS"

  Scenario: LLM returns invalid value on first attempt, valid on retry
    Given an open ingestion stream for run "test-run-011"
    And Claude returns "Finance" on first attempt and "ECONOMICS" on second attempt
    When classify_domain is called with run_id "test-run-011"
    Then the stream contains OBS for CLAIM_DOMAIN with value "ECONOMICS" and status P
    And the stream contains OBS for CLAIM_DOMAIN with value "ECONOMICS" and status F
    And the ClassificationResult has domain="ECONOMICS", confidence="HIGH", attempt_count=2

  Scenario: LLM returns invalid value on both attempts -- fallback to OTHER
    Given an open ingestion stream for run "test-run-012"
    And Claude returns "Business" on both attempts
    When classify_domain is called with run_id "test-run-012"
    Then the stream contains OBS for CLAIM_DOMAIN with value "OTHER" and status F
    And the observation note contains "fallback applied"
    And the ClassificationResult has domain="OTHER", confidence="LOW", attempt_count=2
    And the stream contains a STOP message with finalStatus F

  Scenario: classify_domain called without prior ingest_claim raises error
    Given no open ingestion stream for run "test-run-013"
    When classify_domain is called with run_id "test-run-013"
    Then a StreamStateError is raised
    And no LLM call is made
    And no observations are published

  Scenario: Anthropic API connection error triggers Temporal retry
    Given an open ingestion stream for run "test-run-014"
    And the Anthropic API is unavailable
    When classify_domain is called with run_id "test-run-014"
    Then a ClassificationServiceError is raised
    And the stream does NOT contain a STOP message
    And the Temporal activity is retried

  Scenario: Each domain code is correctly classified
    Given claims representing each domain category
    When classify_domain is called for each claim
    Then the published CLAIM_DOMAIN observation matches the expected domain code for each claim
```
