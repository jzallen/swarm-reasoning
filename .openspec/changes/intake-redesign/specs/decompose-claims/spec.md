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
            "claim_text": str,       # the factual claim — standalone, verifiable sentence
            "quote": str,            # single best sentence from article making the claim
            "citation": {
                "author": str | None,    # person or org attributed (None if unattributed)
                "publisher": str,        # publication name (e.g. "Reuters", "CDC")
                "date": str | None,      # publication date YYYYMMDD if known
            },
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
You are a claim extraction system for a fact-checking pipeline. Given an article's text and metadata, identify up to 5 core factual claims that are suitable for fact-checking.

For each claim, provide three pieces of information:

1. **claim_text**: A specific, verifiable factual assertion rewritten as a standalone sentence. This is what the system will attempt to validate.
2. **quote**: The single best sentence from the article that makes or supports the claim. Choose one sentence even if multiple examples exist. This must be an exact quote from the source text.
3. **citation**: Attribution for the claim — who said it, where it was published, and when.
   - author: The person or organization the claim is attributed to (null if the article makes the claim without attribution)
   - publisher: The name of the publication (provided in article metadata)
   - date: The publication date (provided in article metadata, YYYYMMDD format)

Prioritize claims that are:
- Specific and measurable (contains numbers, dates, named entities)
- Attributed to a named source (person, organization, study)
- Consequential (affects public understanding or policy)

Do NOT include:
- Opinions, predictions, or normative statements
- Claims that are trivially true or common knowledge
- Duplicate or overlapping claims

Return a JSON object with a "claims" array. Each claim has: index (1-5), claim_text, quote, citation.
If the article contains no verifiable factual claims, return {"claims": []}.
Respond with only the JSON object.
```

## Claim Quality Rules

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | Each claim_text is a standalone sentence | System prompt instruction |
| 2 | Each quote is a single exact sentence from the article | Validated in output parsing |
| 3 | Each citation has at least publisher | Validated in output parsing |
| 4 | Claims are deduplicated | System prompt instruction |
| 5 | Maximum 5 claims | Truncate if LLM returns more |
| 6 | Minimum 1 claim for success | Return NO_FACTUAL_CLAIMS if empty |

## Output Parsing

1. Parse LLM response as JSON
2. Validate each claim has required fields (claim_text, quote, citation)
3. Validate citation has at least `publisher`; default `author` to None, `date` to None if missing
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
    And each claim has claim_text, quote, and citation
    And each citation has at least a publisher

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
