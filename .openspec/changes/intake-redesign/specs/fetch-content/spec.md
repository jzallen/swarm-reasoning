# Capability Spec: fetch-content

## Summary

The `fetch-content` capability is a LangChain tool that accepts a URL, validates it is reachable, fetches the page content via HTTP, and extracts readable article text using trafilatura. It is the first tool invoked in the intake pipeline and replaces the old `validate_claim` tool.

## Tool Signature

```python
@tool
async def fetch_content(url: str) -> dict[str, Any]:
    """Fetch and extract readable content from a URL.

    Args:
        url: The URL of the article/post/page to fetch.
    """
```

## Return Schema

```python
# Success
{
    "success": True,
    "url": str,                  # the validated/resolved URL
    "title": str,                # extracted article title
    "text": str,                 # extracted article body text
    "date": str | None,          # publication date if found (YYYYMMDD)
    "word_count": int,           # word count of extracted text
}

# Failure
{
    "success": False,
    "url": str,
    "error": str,                # one of the error codes below
    "detail": str,               # human-readable error message
}
```

## Validation Rules

| # | Rule | Condition | Error Code |
|---|------|-----------|------------|
| 1 | URL format | Matches `^https?://[^\s]+\.[^\s]{2,}$` | `URL_INVALID_FORMAT` |
| 2 | URL reachable | HTTP GET returns 2xx within 10s timeout | `URL_UNREACHABLE` |
| 3 | Content type | Response Content-Type contains `text/html` | `URL_NOT_HTML` |
| 4 | Content extractable | Trafilatura extracts non-empty text | `CONTENT_EXTRACTION_FAILED` |
| 5 | Minimum content | Extracted text >= 50 words | `CONTENT_TOO_SHORT` |

## Content Extraction

1. HTTP GET with `User-Agent: SwarmReasoning/1.0` and 10s timeout
2. Pass response body to `trafilatura.extract()` with `include_comments=False`, `include_tables=True`
3. If trafilatura returns None, fallback to BeautifulSoup `get_text()`
4. If fallback also produces empty text, return error `CONTENT_EXTRACTION_FAILED`
5. Extract title via `trafilatura.extract()` metadata or `<title>` tag
6. Extract publication date via trafilatura metadata, normalize to YYYYMMDD if found

## Progress Events

Uses `get_stream_writer()`:
- `"Validating URL..."` — before HTTP request
- `"Fetching article content..."` — during HTTP request
- `"Extracting text ({word_count} words)..."` — after successful extraction
- `"URL error: {error_code}"` — on failure

## Error Handling

| Error | Behavior |
|-------|----------|
| `httpx.TimeoutException` | Return error `URL_UNREACHABLE` with detail |
| `httpx.HTTPStatusError` (4xx/5xx) | Return error `URL_UNREACHABLE` with status code |
| `ssl.SSLError` | Return error `URL_UNREACHABLE` with SSL detail |
| Trafilatura + BeautifulSoup both fail | Return error `CONTENT_EXTRACTION_FAILED` |

No exceptions are raised — all errors return structured error dicts so the agent can reason about them.

## Dependencies

- `httpx` — async HTTP client (already in project)
- `trafilatura` — article text extraction (new dependency)
- `beautifulsoup4` — fallback text extraction (already in project)

## Gherkin Acceptance Criteria

```gherkin
Feature: Fetch Content

  Scenario: Valid news article URL is fetched and extracted
    Given a URL "https://example.com/article"
    And the URL returns HTML with a news article
    When fetch_content is called
    Then the result has success=True
    And text contains the article body
    And word_count >= 50
    And title is extracted

  Scenario: Invalid URL format is rejected
    Given a URL "not-a-url"
    When fetch_content is called
    Then the result has success=False and error="URL_INVALID_FORMAT"

  Scenario: Unreachable URL returns error
    Given a URL "https://nonexistent.example.com/page"
    When fetch_content is called
    Then the result has success=False and error="URL_UNREACHABLE"

  Scenario: Non-HTML content type is rejected
    Given a URL that returns Content-Type "application/pdf"
    When fetch_content is called
    Then the result has success=False and error="URL_NOT_HTML"

  Scenario: Page with too little content
    Given a URL that returns HTML with only 10 words of content
    When fetch_content is called
    Then the result has success=False and error="CONTENT_TOO_SHORT"
```
