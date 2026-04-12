## Context

ADR-0019 specifies that when a verdict is finalized, the NestJS backend renders a self-contained static HTML document containing two toggled views: verdict summary and chat progress log. The snapshot is stored on S3 (local filesystem in dev) and served directly when users revisit the session URL. Sessions are ephemeral with a 3-day TTL.

Key constraints from architecture docs:
- ADR-0019: Static HTML snapshots -- self-contained, no external JS framework, print-friendly
- ADR-0014: NestJS backend renders the HTML (server-side, not the frontend SPA)
- ADR-0020: S3 + CloudFront for snapshot hosting in production
- Session entity: status `active -> frozen -> expired`, 3-day TTL
- Verdict entity: factuality score, rating label, narrative, citations
- ProgressEvent entity: chronological agent messages from `progress:{runId}` stream
- NFR-030: Render time < 5000ms

## Goals / Non-Goals

**Goals:**
- Render a self-contained HTML document from verdict + progress event data
- Two views toggled by inline JavaScript: verdict summary and chat progress log
- Store snapshots on S3 (production) or local filesystem (dev)
- Integrate with session finalization flow
- Implement scheduled cleanup for expired sessions
- Print-friendly layout
- Meet NFR-030 render time target

**Non-Goals:**
- Using a JavaScript framework in the rendered HTML (explicit ADR-0019 constraint)
- Server-side rendering of the live SPA (that is the frontend's domain)
- Real-time updates in the snapshot (it is frozen by definition)
- PDF generation (rejected by ADR-0019)
- Snapshot versioning or edit history

## Decisions

### 1. Template-based HTML rendering with string interpolation

The renderer uses a TypeScript template function that accepts verdict and progress event data and produces an HTML string. No template engine library (Handlebars, EJS) is needed -- tagged template literals in TypeScript are sufficient for this single-template use case. The template is a single function in a single file, making it easy to test and maintain.

**Alternative considered:** Handlebars/EJS template engine. Rejected -- adds a dependency for a single template; TypeScript template literals are type-safe and testable.

### 2. Tab toggle via inline JavaScript

The two views (verdict and chat) are both rendered in the HTML as sibling `<section>` elements. One is visible, one is hidden via `display: none`. A tab bar at the top with two buttons toggles visibility using a 10-line inline `<script>` block. No external JavaScript, no framework, no module loading.

**Alternative considered:** Two separate HTML pages. Rejected -- increases storage cost and complicates the URL model; a single document with tabs is simpler.

### 3. All styles inline via `<style>` block

CSS is embedded in a `<style>` element in the `<head>`. No external stylesheet. This ensures the snapshot is completely self-contained -- it renders correctly when opened from a local file, served from S3, or cached by a CDN. Print styles use `@media print` to hide the tab bar and show both views sequentially.

### 4. SnapshotStore interface with S3 and local implementations

The `SnapshotStore` interface defines two methods: `store(sessionId: string, html: string): Promise<string>` (returns the URL) and `delete(sessionId: string): Promise<void>`. Two implementations:

- `S3SnapshotStore`: Uploads to `s3://{bucket}/snapshots/{sessionId}.html` with `Content-Type: text/html`, `Cache-Control: public, max-age=259200` (3 days). Returns the CloudFront URL.
- `LocalSnapshotStore`: Writes to `data/snapshots/{sessionId}.html` on the local filesystem. Returns a relative URL served by NestJS static file middleware.

The active implementation is selected by environment variable (`SNAPSHOT_STORE=s3|local`), defaulting to `local`.

**Alternative considered:** Always use S3 with LocalStack for dev. Rejected -- adds a container to the dev stack for no benefit; local filesystem is simpler.

### 5. FinalizeSessionUseCase orchestrates the full finalization sequence

After the synthesizer emits the verdict, the `FinalizeSessionUseCase` executes:
1. Read verdict data from PostgreSQL (persisted by the orchestrator)
2. Read all progress events from Redis Stream `progress:{runId}` via `XRANGE`
3. Call `StaticHtmlRenderer.render(verdict, progressEvents)` to produce HTML
4. Call `SnapshotStore.store(sessionId, html)` to persist the snapshot
5. Update session: set `snapshotUrl`, `frozenAt`, `expiresAt` (now + 3 days), status = `frozen`
6. Publish `session-frozen` event to `progress:{runId}` (triggers SSE close)

This is a sequential pipeline -- each step depends on the previous.

### 6. CleanupExpiredSessionsUseCase as a Temporal scheduled workflow

A Temporal scheduled workflow runs daily (or every 6 hours for tighter cleanup). It queries PostgreSQL for sessions where `expiresAt < now()`, then for each expired session:
1. Delete the snapshot via `SnapshotStore.delete(sessionId)`
2. Delete Redis streams: `progress:{runId}`, all `reasoning:{runId}:*` streams
3. Delete database rows: citations, verdict, session (cascade)

**Alternative considered:** PostgreSQL `pg_cron`. Rejected -- requires a PostgreSQL extension; Temporal is already in the stack and provides retry, visibility, and scheduling.

### 7. Verdict view layout

The verdict section contains:
- Header with "Fact Check Verdict" title
- Factuality score displayed as a large number with a circular gauge or meter visual (pure CSS)
- Rating label as a color-coded badge
- Narrative as a prose paragraph
- Citation table with columns: #, Source, Agent, Code, Status, Cited By (convergence count)
- Validation status shown as colored dot + text label

### 8. Chat progress view layout

The chat section contains:
- Header with "Agent Progress Log" title
- Chronological list of progress messages, each showing: agent name (bold), phase badge (colored), message text, timestamp (gray, right-aligned)
- Visual grouping by phase (ingestion, fanout, synthesis, finalization) with phase separator bars

## Risks / Trade-offs

- **[Template maintenance]** Changes to the verdict schema or progress event format require updating the HTML template. Mitigation: the template is a single TypeScript function with typed inputs; compile-time checks catch field changes.
- **[Large snapshots]** Sessions with many progress events may produce large HTML files. Mitigation: progress messages are short text strings; even 100 messages at 200 chars each is ~20KB of content, well within acceptable limits.
- **[S3 eventual consistency]** After uploading, the snapshot URL may not resolve immediately. Mitigation: CloudFront caching handles this; the session status is checked first (if frozen, snapshot exists).
- **[Cleanup race condition]** If a user is viewing a snapshot when the cleanup job runs, the snapshot is deleted mid-view. Mitigation: the browser has already loaded the full HTML document; deleting the S3 object does not affect the rendered page.
