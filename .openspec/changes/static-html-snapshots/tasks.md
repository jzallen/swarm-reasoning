## 1. SnapshotStore Interface and Local Implementation

- [x] 1.1 Create `src/application/ports/snapshot-store.port.ts` with interface: `store(sessionId, html): Promise<string>`, `delete(sessionId): Promise<void>`, `exists(sessionId): Promise<boolean>`
- [x] 1.2 Create `src/infrastructure/adapters/local-snapshot-store.adapter.ts`: writes to `data/snapshots/{sessionId}.html`, returns `/snapshots/{sessionId}.html`
- [x] 1.3 Implement `delete()` (remove file) and `exists()` (check file); handle missing file gracefully on delete
- [ ] 1.4 Create `data/snapshots/.gitkeep`; configure NestJS `ServeStaticModule` to serve `data/snapshots/` at `/snapshots/`

## 2. S3 Snapshot Store Implementation

- [x] 2.1 Create `src/infrastructure/adapters/s3-snapshot-store.adapter.ts`: uploads to `s3://{bucket}/snapshots/{sessionId}.html` with `Content-Type: text/html; charset=utf-8`, `Cache-Control: public, max-age=259200`
- [x] 2.2 Return CloudFront URL; implement `delete()` via DeleteObject and `exists()` via HeadObject
- [x] 2.3 Configure AWS SDK from env vars: `AWS_REGION`, `S3_BUCKET_NAME`, `CLOUDFRONT_DOMAIN`; add `@aws-sdk/client-s3` dependency

## 3. Snapshot Store Module

- [x] 3.1 Create `src/infrastructure/snapshot/snapshot-store.module.ts` with factory provider: `SNAPSHOT_STORE=s3` -> S3, else -> Local
- [x] 3.2 Export `SnapshotStore` token for injection; add `SNAPSHOT_STORE` to `.env.example`

## 4. Static HTML Renderer

- [x] 4.1 Create `src/infrastructure/renderers/static-html.renderer.ts` with `render(verdict, progressEvents, session): string`
- [x] 4.2 Render HTML5 wrapper: `<!DOCTYPE html>`, `<html lang="en">`, viewport meta, charset meta
- [x] 4.3 Embed all CSS in `<style>` block: layout, typography, colors, table styles, rating badge colors
- [x] 4.4 Render tab bar with two buttons ("Verdict" and "Agent Progress") and inline `<script>` for toggle (~10 lines)
- [x] 4.5 Render verdict section: session ID, claim text, factuality score KPI, rating label badge, narrative, signal count, finalized timestamp
- [x] 4.6 Render citation table: columns (#, Source, Agent, Code, Validation Status, Convergence); sorted by convergence descending; status as colored dot + text
- [x] 4.7 Render chat progress section (initially hidden): phase group headers, each event with agent name (bold), phase badge, message, timestamp
- [x] 4.8 Render print button calling `window.print()`

## 5. Print Styles

- [x] 5.1 Add `@media print` rules: hide tab bar and print button; show both sections sequentially
- [x] 5.2 Add page break between verdict and chat sections; `break-inside: avoid` on citation table

## 6. FinalizeSessionUseCase Integration

- [x] 6.1 Inject `StaticHtmlRenderer` and `SnapshotStore` into `FinalizeSessionUseCase`
- [x] 6.2 After persisting verdict: read all progress events from Redis via `XRANGE('0', '+')`
- [x] 6.3 Call `render(verdict, progressEvents, session)` then `store(sessionId, html)`
- [x] 6.4 Update session: set `snapshotUrl`, `frozenAt`, `expiresAt` (now + 3 days), status = `frozen`
- [x] 6.5 Publish `session-frozen` progress event to `progress:{runId}`
- [x] 6.6 Log render + store duration for NFR-030 monitoring

## 7. CleanupExpiredSessionsUseCase

- [x] 7.1 Create `src/application/use-cases/cleanup-expired-sessions.use-case.ts`
- [x] 7.2 Query for sessions where `status = 'frozen'` and `expiresAt < NOW()`
- [x] 7.3 For each: delete snapshot, delete Redis streams (`progress:{runId}`, `reasoning:{runId}:*`), cascade-delete DB rows
- [x] 7.4 Handle partial failures: log and continue to next session; return success/failure summary
- [x] 7.5 Ensure idempotent: re-running on partially cleaned session does not error

## 8. Cleanup Scheduling

- [ ] 8.1 Implement as Temporal scheduled workflow (every 6 hours) calling cleanup as activity
- [x] 8.2 Alternative: NestJS cron job with `@Cron('0 */6 * * *')` if Temporal scheduling unavailable

## 9. Session Entity Updates

- [x] 9.1 Verify `snapshotUrl` (nullable string) and `expiresAt` (nullable datetime) fields on session entity
- [x] 9.2 Add TypeORM migration if fields not present; update entity definition

## 10. Unit Tests

- [x] 10.1 Test `StaticHtmlRenderer.render()`: valid HTML output with both sections, tab script, correct data
- [x] 10.2 Test citation table sorted by convergence; print styles hide tab bar
- [ ] 10.3 Test `LocalSnapshotStore`: mock filesystem, verify write/read/delete
- [ ] 10.4 Test `S3SnapshotStore`: mock AWS SDK, verify PutObject params
- [x] 10.5 Test `CleanupExpiredSessionsUseCase`: 0, 1, N expired sessions; partial failure handling

## 11. Integration Tests

- [ ] 11.1 Test full finalization: persist verdict -> render -> store -> verify frozen session with snapshotUrl
- [ ] 11.2 Test cleanup: create expired sessions, run cleanup, verify all resources deleted
- [ ] 11.3 Test NFR-030: render time < 5000ms for typical verdict with 50 progress events
- [ ] 11.4 Test HTML output: parse rendered HTML, verify both sections, no external resource references
