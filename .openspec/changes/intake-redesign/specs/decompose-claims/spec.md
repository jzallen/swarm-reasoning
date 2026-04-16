# Capability Spec: decompose-claims

## Summary

The `decompose-claims` capability is an LLM-powered LangChain tool that analyzes article text and extracts up to 5 core factual claims suitable for fact-checking. It receives a `ChatAnthropic` model instance via closure and forwards `RunnableConfig` for tracing.

## Tool Signature

```python
@tool
async def decompose_claims(article_text: str, article_title: str, config: RunnableConfig) -> dict[str, Any]:
    """Extract up to 5 factual claims from article text.

    Args:
        article_text: The extracted article body text.
        article_title: The article title for context.
        config: RunnableConfig for tracing propagation.
    """
```

## Return Schema

```python
# Success
{
    "claims": [
        {
            "index": int,            # 1-5
            "claim_text": str,       # the factual claim, standalone sentence
            "source_quote": str,     # exact quote from article
            "category": str,         # preliminary domain hint
        },
        ...
    ],
    "article_title": str,
    "article_date": str | None,      # YYYYMMDD if extractable
    "claim_count": int,              # number of claims found
}

# Failure (article not decomposable)
{
    "claims": [],
    "article_title": str,
    "article_date": None,
    "claim_count": 0,
    "error": "NO_FACTUAL_CLAIMS",
}
```

## LLM Configuration

- Model: `ChatAnthropic(model=DECOMPOSE_MODEL)` where `DECOMPOSE_MODEL = "claude-sonnet-4-6"`
- Invoked via: `model.ainvoke(messages, config)` — config forwarded from tool parameter
- Temperature: 0 (set on the model instance in agent builder)
- Max tokens: 2048

## System Prompt

```
You are a claim extraction system for a fact-checking pipeline. Given an article's text, identify up to 5 core factual claims that are suitable for fact-checking.

For each claim:
1. Extract a specific, verifiable factual assertion as a standalone sentence
2. Include the exact quote from the article that contains or supports the claim
3. Assign a preliminary domain category: HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, or OTHER

Prioritize claims that are:
- Specific and measurable (contains numbers, dates, named entities)
- Attributed to a source (person, organization, study)
- Consequential (affects public understanding or policy)

Do NOT include:
- Opinions, predictions, or normative statements
- Claims that are trivially true or common knowledge
- Duplicate or overlapping claims

Return a JSON object with a "claims" array. Each claim has: index (1-5), claim_text, source_quote, category.
If the article contains no verifiable factual claims, return {"claims": []}.
Respond with only the JSON object.
```

## Claim Quality Rules

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | Each claim is a standalone sentence | System prompt instruction |
| 2 | Each claim has an exact source quote | Validated in output parsing |
| 3 | Claims are deduplicated | System prompt instruction |
| 4 | Maximum 5 claims | Truncate if LLM returns more |
| 5 | Minimum 1 claim for success | Return NO_FACTUAL_CLAIMS if empty |
| 6 | Category is from controlled vocabulary | Validate against DOMAIN_VOCABULARY, default to OTHER |

## Output Parsing

1. Parse LLM response as JSON
2. Validate each claim has required fields (claim_text, source_quote, category)
3. Validate category against `DOMAIN_VOCABULARY`; default unrecognized to `OTHER`
4. Truncate to 5 claims if more returned
5. On JSON parse failure: retry once, then return `NO_FACTUAL_CLAIMS` error

## Progress Events

Uses `get_stream_writer()`:
- `"Analyzing article for factual claims..."` — before LLM call
- `"Found {n} claims for review"` — after successful extraction

## Gherkin Acceptance Criteria

```gherkin
Feature: Decompose Claims

  Scenario: News article produces 5 factual claims
    Given article text from a news article with multiple factual assertions
    When decompose_claims is called
    Then the result has claim_count between 1 and 5
    And each claim has claim_text, source_quote, and category
    And each category is a valid domain code

  Scenario: Opinion article produces no factual claims
    Given article text that contains only opinions and predictions
    When decompose_claims is called
    Then the result has claim_count=0 and error="NO_FACTUAL_CLAIMS"

  Scenario: Short article produces fewer than 5 claims
    Given article text with only 2 verifiable facts
    When decompose_claims is called
    Then the result has claim_count=2

  Scenario: LLM returns malformed JSON on first attempt
    Given article text and the LLM returns non-JSON on first call
    When decompose_claims is called
    Then the tool retries once
    And returns claims if retry succeeds or NO_FACTUAL_CLAIMS if retry fails
```
