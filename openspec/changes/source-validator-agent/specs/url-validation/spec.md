## ADDED Requirements

### Requirement: HTTP HEAD validation for each extracted URL

The source-validator agent SHALL validate each extracted URL by issuing an HTTP HEAD request via `httpx.AsyncClient`. The request SHALL have a 5-second timeout and follow redirects up to 5 hops. The validation result is classified into one of five statuses.

Validation status classification:
- HTTP 200 (and not soft-404) -> `LIVE^Live^FCK`
- HTTP 3xx (redirect chain resolved) -> `REDIRECT^Redirect^FCK`
- HTTP 4xx or 5xx -> `DEAD^Dead^FCK`
- Request timeout or connection error -> `TIMEOUT^Timeout^FCK`
- HTTP 200 with soft-404 content -> `SOFT404^Soft 404^FCK`

#### Scenario: Live URL returns 200

- **GIVEN** the URL "https://www.reuters.com/article/123" returns HTTP 200 with normal content
- **WHEN** URL validation runs
- **THEN** validation status = "LIVE^Live^FCK"

#### Scenario: Dead URL returns 404

- **GIVEN** the URL "https://example.com/removed-article" returns HTTP 404
- **WHEN** URL validation runs
- **THEN** validation status = "DEAD^Dead^FCK"

#### Scenario: URL redirects to new location

- **GIVEN** the URL returns HTTP 301 -> HTTP 302 -> HTTP 200
- **WHEN** URL validation runs
- **THEN** validation status = "REDIRECT^Redirect^FCK"
- **AND** the final URL is recorded in the ValidationResult

#### Scenario: URL times out

- **GIVEN** the URL does not respond within 5 seconds
- **WHEN** URL validation runs
- **THEN** validation status = "TIMEOUT^Timeout^FCK"

---

### Requirement: Soft-404 detection

When an HTTP 200 response is received, the agent SHALL fetch the first 2KB of the response body via a GET request and check for soft-404 indicators. A URL is classified as SOFT404 if any of these conditions are met:

Page title indicators (case-insensitive):
- "page not found"
- "404"
- "not found"
- "no longer available"

Body text indicators (case-insensitive):
- "this page doesn't exist"
- "the page you requested"
- "has been removed"

#### Scenario: Soft-404 page returns 200 but shows "Page Not Found"

- **GIVEN** the URL returns HTTP 200
- **AND** the page title contains "Page Not Found"
- **WHEN** soft-404 detection runs
- **THEN** validation status = "SOFT404^Soft 404^FCK"

#### Scenario: Legitimate page with "not found" in body content

- **GIVEN** the URL returns HTTP 200
- **AND** the body mentions "The study found that..." (not a 404 indicator)
- **AND** the page title is "Clinical Study Results"
- **WHEN** soft-404 detection runs
- **THEN** validation status = "LIVE^Live^FCK" (not a false positive)

---

### Requirement: HEAD to GET fallback

If an HTTP HEAD request returns HTTP 405 (Method Not Allowed), the agent SHALL retry the request as an HTTP GET with a 1KB body read limit. The GET response status code is used for classification.

#### Scenario: Server does not support HEAD

- **GIVEN** the server returns HTTP 405 for HEAD
- **WHEN** the agent retries with GET
- **AND** GET returns HTTP 200
- **THEN** validation status = "LIVE^Live^FCK"

---

### Requirement: Concurrent URL validation with bounded concurrency

URL validation SHALL run concurrently using `asyncio.Semaphore(10)` to limit concurrent HTTP connections. This prevents overwhelming target servers and keeps resource usage bounded. With typical URL counts (5-15), validation completes within the 45-second Phase 2 budget.

#### Scenario: 15 URLs validated concurrently

- **GIVEN** 15 extracted URLs, all responding within 1 second
- **WHEN** concurrent validation runs with semaphore(10)
- **THEN** all 15 URLs are validated in approximately 2 seconds (2 batches of 10 + 5)
- **AND** total validation time is well under the 45-second budget

---

### Requirement: SOURCE_VALIDATION_STATUS observations

For each validated URL, the agent SHALL publish one SOURCE_VALIDATION_STATUS observation (CWE type, status = F). The CWE value encodes the validation result. Observations are published via the `publish_observation` tool (ADR-0004).

#### Scenario: Validation results published for all URLs

- **GIVEN** 5 URLs were extracted and validated (3 LIVE, 1 DEAD, 1 TIMEOUT)
- **WHEN** observations are published
- **THEN** 5 SOURCE_VALIDATION_STATUS observations are emitted
- **AND** values are: 3x "LIVE^Live^FCK", 1x "DEAD^Dead^FCK", 1x "TIMEOUT^Timeout^FCK"
- **AND** all have status = F and agent = "source-validator"

---

### Requirement: Progress events during validation

The agent SHALL publish progress events to `progress:{runId}` during URL validation: "Validating source URLs..." at start, "Validated {n}/{total} URLs" at 50% and 100% completion.

#### Scenario: Progress during 10-URL validation

- **GIVEN** 10 URLs to validate
- **WHEN** validation progresses
- **THEN** progress events include "Validating source URLs...", "Validated 5/10 URLs", and "Validated 10/10 URLs"
