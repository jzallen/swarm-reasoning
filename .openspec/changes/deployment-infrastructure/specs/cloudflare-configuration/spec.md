## ADDED Requirements

### Requirement: Cloudflare DNS proxy with SSL Full (Strict)

Cloudflare SHALL be configured as the DNS proxy for the application domain. SSL mode SHALL be set to Full (Strict), requiring a valid certificate on the origin (ALB with ACM certificate). Minimum TLS version SHALL be 1.2. HSTS SHALL be enabled.

#### Scenario: DNS records configured

- **GIVEN** the Cloudflare DNS configuration
- **WHEN** the records are inspected
- **THEN** a CNAME record points the application domain to the ALB DNS name
- **AND** proxy mode is enabled (orange cloud)

#### Scenario: SSL Full (Strict) mode

- **GIVEN** the Cloudflare SSL configuration
- **WHEN** the settings are inspected
- **THEN** SSL mode is `full_strict`
- **AND** minimum TLS version is `1.2`
- **AND** HSTS is enabled with `max-age=31536000`

### Requirement: Rate limiting on claim submission endpoint

A Cloudflare rate limiting rule SHALL cap claim submissions to 10 requests per minute per IP address. The rule SHALL apply to `POST` requests matching the path pattern `/sessions/*/claims`.

#### Scenario: Rate limit enforced

- **GIVEN** the Cloudflare rate limiting rule
- **WHEN** a single IP sends 11 `POST /sessions/{id}/claims` requests within 60 seconds
- **THEN** the 11th request receives a 429 Too Many Requests response
- **AND** subsequent requests from that IP are blocked for the remainder of the 60-second window

#### Scenario: Rate limit does not affect other endpoints

- **GIVEN** the Cloudflare rate limiting rule
- **WHEN** a single IP sends 50 `GET /sessions/{id}` requests within 60 seconds
- **THEN** all 50 requests are allowed (rate limit applies only to claim submission)

### Requirement: Cache rules for static assets and API bypass

Cloudflare caching rules SHALL cache static frontend assets (JS, CSS, images) and bypass caching for API endpoints and SSE streams.

#### Scenario: Static assets are cached

- **GIVEN** the Cloudflare cache rules
- **WHEN** a request for `/assets/main.js` is made
- **THEN** the response is served from Cloudflare edge cache on subsequent requests

#### Scenario: API endpoints bypass cache

- **GIVEN** the Cloudflare cache rules
- **WHEN** a request for `/sessions/{id}` is made
- **THEN** the request is forwarded to the origin (not cached)

#### Scenario: SSE endpoint not buffered

- **GIVEN** the Cloudflare configuration and SSE response headers
- **WHEN** a request for `/sessions/{id}/events` returns with `X-Accel-Buffering: no`
- **THEN** the response is streamed directly to the client without Cloudflare buffering
