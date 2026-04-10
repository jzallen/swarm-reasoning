## Why

After the synthesizer emits a final verdict, the session transitions to `frozen`. Users who revisit the session URL need to see the results without requiring the live frontend or a running SSE connection. ADR-0019 specifies that the backend renders a self-contained static HTML document with two toggled views (verdict summary and chat progress log), stores it on S3 (local filesystem in dev), and serves it directly. Frozen sessions are ephemeral with a 3-day TTL, after which all associated data is cleaned up. This slice implements the HTML rendering, snapshot storage, session finalization, and expiration cleanup.

## What Changes

- Implement `StaticHtmlRenderer` in NestJS infrastructure layer: takes verdict data + progress events, produces a self-contained HTML string with inline CSS and inline JS for tab toggling
- Two views in one HTML file: (1) Verdict summary with factuality score KPI, rating badge, narrative, citation table (2) Chat progress log with all agent messages rendered chronologically
- Implement `S3SnapshotStore` (interface + two implementations): S3 upload for production, local filesystem write for dev
- Integrate with `FinalizeSessionUseCase`: after verdict is ready, render snapshot, store it, update `session.snapshotUrl`, transition session to `frozen`
- Implement `CleanupExpiredSessionsUseCase`: scheduled Temporal workflow or cron that finds sessions older than 3 days and deletes: database rows, snapshot files, Redis streams
- Print button in the rendered HTML triggers `window.print()`
- No external JS framework in the snapshot -- vanilla HTML + minimal inline CSS + inline JS for tab toggle
- NFR-030: snapshot render time < 5000ms

## Capabilities

### New Capabilities

- `html-renderer`: Server-side HTML template engine that produces a self-contained document from verdict and progress event data. Two toggled views: verdict summary and chat log. All styles inline, no external dependencies. Print-friendly layout via CSS `@media print`.
- `snapshot-storage`: Abstraction layer for storing and retrieving rendered HTML snapshots. S3 implementation for production (with 3-day lifecycle policy). Local filesystem implementation for development (writes to `data/snapshots/`).
- `session-cleanup`: Scheduled process that identifies expired sessions (frozen > 3 days) and deletes all associated resources: PostgreSQL rows (session, verdict, citations), snapshot file (S3 or local), Redis streams (`progress:{runId}`, `reasoning:{runId}:*`).

### Modified Capabilities

- `finalize-session` (from orchestrator-core): Extended to call the HTML renderer and snapshot store after persisting the verdict, then update `session.snapshotUrl` and set `session.expiresAt`.

## Impact

- **New files**: `StaticHtmlRenderer`, `S3SnapshotStore`, `LocalSnapshotStore`, `SnapshotStoreInterface`, `CleanupExpiredSessionsUseCase`, HTML template, snapshot store module
- **Modified files**: `FinalizeSessionUseCase` (add render + store step), session entity (add `snapshotUrl`, `expiresAt` fields if not present)
- **New dev directory**: `data/snapshots/` for local filesystem snapshot storage
- **No new containers**: Runs within the existing `backend` service
