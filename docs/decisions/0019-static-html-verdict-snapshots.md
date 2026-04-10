---
status: accepted
date: 2026-04-10
deciders: []
---

# ADR-0019: Static HTML Verdict Snapshots with Ephemeral Sessions

## Context and Problem Statement

This is a portfolio project with no user accounts. Users submit a claim, watch agents work via SSE progress updates (ADR-0018), and receive a verdict. After the verdict is final, no further interaction is needed. Users should be able to leave and return via the session URL to view the result. Results are retained for 3 days.

## Decision Drivers

- Portfolio project -- ephemeral by design, no authentication overhead
- Minimal infrastructure cost for result storage
- Results must be viewable without running the frontend application or loading a JavaScript framework
- Print-friendly output for offline reference

## Considered Options

1. **Client-side freeze** -- Store the verdict JSON in the database, re-hydrate on revisit using the frontend SPA. Requires the full frontend bundle to load and parse the JSON into a rendered view.
2. **Server-rendered static HTML** -- Self-contained HTML document with inline CSS and minimal client-side JavaScript for view toggling. No framework dependency to view the result.
3. **PDF generation** -- Render the verdict as a PDF document. More official appearance but heavier to generate, harder to toggle between views, and requires a headless browser or PDF library on the backend.

## Decision Outcome

Chosen option: "Server-rendered static HTML", because it produces a self-contained document that needs no JavaScript framework to view, supports native browser printing, and is trivially cacheable on a CDN.

When the synthesizer emits the final verdict, the NestJS backend renders a static HTML document containing two views toggled by client-side JavaScript:

1. **Verdict summary** -- Factuality score, KPI display, and citation list with annotated sources.
2. **Chat progress log** -- The full SSE progress stream rendered as a conversation transcript.

The static HTML is stored on S3 (local filesystem in dev) and served directly when users revisit the session URL. A print button triggers the browser's native print dialog. A scheduled cleanup (Temporal scheduled workflow or cron) deletes sessions, snapshots, and database rows older than 3 days.

No login, no user management, no persistent accounts.

### Consequences

- Good, because static HTML needs no JavaScript framework to view and prints natively via the browser
- Good, because S3 hosting is near-zero cost and CloudFront or Cloudflare can cache and serve from edge locations
- Bad, because the HTML rendering template must be maintained alongside any changes to the verdict schema or progress message format
- Neutral, because the 3-day TTL means no long-term storage cost and no GDPR-style data retention concerns

## More Information

- ADR-0018: SSE Relay for Real-Time Progress (live progress before the snapshot is generated)
- ADR-0014: Three-Service Architecture (backend renders the static HTML)
- ADR-0020: Cloudflare + AWS ECS Fargate Deployment (S3 + CloudFront hosting for snapshots)
