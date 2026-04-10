## 1. Project Scaffolding

- [ ] 1.1 Initialize `services/frontend/` with Vite + React + TypeScript template
- [ ] 1.2 Configure `vite.config.ts`: server port 5173, proxy `/api` to `http://backend:3000`
- [ ] 1.3 Set up `tsconfig.json` with strict mode and path aliases (`@/` -> `src/`)
- [ ] 1.4 Configure ESLint, Prettier, and `package.json` scripts (`dev`, `build`, `lint`, `format`)
- [ ] 1.5 Create `index.html` with viewport meta, root div; create `src/main.tsx` entry point
- [ ] 1.6 Verify `npm run dev` starts on port 5173

## 2. API Client Module

- [ ] 2.1 Create `src/api/client.ts` with base URL configuration (defaults to `http://localhost:3000`)
- [ ] 2.2 Implement `createSession()`, `getSession(sessionId)`, `submitClaim(sessionId, claimText)`, `getVerdict(sessionId)` using native `fetch`
- [ ] 2.3 Create `src/api/types.ts` with interfaces matching OpenAPI schemas: `Session`, `Claim`, `Verdict`, `Citation`, `ProgressEvent`, `ErrorResponse`
- [ ] 2.4 Add typed error handling for 404, 422, 503 responses

## 3. Session State Management

- [ ] 3.1 Create `src/hooks/useSession.ts` with `useReducer` managing states: `idle`, `creating`, `active`, `verdict`, `frozen`, `error`
- [ ] 3.2 Define actions: `SESSION_CREATED`, `CLAIM_SUBMITTED`, `PROGRESS_EVENT`, `VERDICT_RECEIVED`, `SESSION_FROZEN`, `ERROR`
- [ ] 3.3 Store progress events array and verdict in state
- [ ] 3.4 On page load: parse URL pathname for session ID, fetch session status if present, set state accordingly

## 4. SSE Client Hook

- [ ] 4.1 Create `src/hooks/useSSE.ts` wrapping native `EventSource` for `GET /sessions/{sessionId}/events`
- [ ] 4.2 Register listeners for `progress`, `verdict`, `close` event types; parse JSON data; dispatch to state
- [ ] 4.3 On `close` event: close EventSource, dispatch `SESSION_FROZEN`
- [ ] 4.4 Handle `onerror`: rely on native auto-reconnect (sends Last-Event-ID automatically)
- [ ] 4.5 Clean up EventSource on unmount; skip connection for `frozen` or `idle` states

## 5. App Component and URL Handling

- [ ] 5.1 Create `src/App.tsx`: parse pathname for session ID, render landing/active/verdict/frozen view
- [ ] 5.2 After session creation: update URL via `window.history.pushState`
- [ ] 5.3 Handle browser back/forward via `popstate` event listener

## 6. Chat Interface Component

- [ ] 6.1 Create `src/components/ChatInterface.tsx` with scrolling message container and claim input form
- [ ] 6.2 On submit: call `createSession()` then `submitClaim()`, update URL, start SSE
- [ ] 6.3 Disable input after submission; show submitted claim as first message (user-style, right-aligned)
- [ ] 6.4 Show "Connecting to agents..." placeholder before first SSE event
- [ ] 6.5 Auto-scroll to bottom on new messages
- [ ] 6.6 Create `src/components/ChatInterface.module.css`

## 7. Progress Bubble Component

- [ ] 7.1 Create `src/components/ProgressBubble.tsx` rendering agent name (bold), phase badge (colored), message text, timestamp
- [ ] 7.2 Phase badge colors: blue (ingestion), green (fanout), purple (synthesis), gray (finalization)
- [ ] 7.3 Style `agent-started`/`agent-completed` as italic/lighter; `agent-progress` as normal
- [ ] 7.4 Create `src/components/ProgressBubble.module.css`

## 8. Verdict Display Component

- [ ] 8.1 Create `src/components/VerdictDisplay.tsx` with factuality score KPI (large number), color-coded rating badge, narrative text, signal count
- [ ] 8.2 Rating badge colors: green (true, mostly-true), yellow (half-true), orange (mostly-false), red (false, pants-on-fire)
- [ ] 8.3 Create `src/components/VerdictDisplay.module.css`

## 9. Citation Table Component

- [ ] 9.1 Create `src/components/CitationTable.tsx` with columns: Source Name, URL (linked, target=_blank), Agent, Code, Status (icon + label), Convergence
- [ ] 9.2 Sort by convergence count descending; validation status icons: green (live), red (dead), yellow (redirect/soft-404/timeout), gray (not-validated)
- [ ] 9.3 Mobile: horizontal scroll on table container
- [ ] 9.4 Create `src/components/CitationTable.module.css`

## 10. Frozen Session / Snapshot View

- [ ] 10.1 Create `src/components/SnapshotView.tsx`: render iframe with `src={snapshotUrl}` filling content area
- [ ] 10.2 Handle missing snapshot: show fallback message; handle expired sessions: show expiration message
- [ ] 10.3 Create `src/components/SnapshotView.module.css`

## 11. Print and Layout

- [ ] 11.1 Create `src/components/PrintButton.tsx`: renders "Print" button calling `window.print()`; visible only with verdict or frozen session
- [ ] 11.2 Create `src/styles/global.css`: color tokens for PolitiFact scale, responsive breakpoints (mobile <640px, tablet 640-1024px, desktop >1024px)
- [ ] 11.3 Chat container: centered max-width 720px on desktop, full-width on mobile
- [ ] 11.4 Add `@media print` styles: hide print button, input area, navigation

## 12. Error Handling UI

- [ ] 12.1 Create `src/components/ErrorBanner.tsx` for API errors (503, 422, 404) and SSE connection failures
- [ ] 12.2 Show "Session not found" page for invalid session IDs

## 13. Unit Tests

- [ ] 13.1 Test API client: mock fetch, verify URL construction, error handling
- [ ] 13.2 Test `useSession` hook: verify full lifecycle state transitions
- [ ] 13.3 Test `useSSE` hook: mock EventSource, verify event parsing and dispatch
- [ ] 13.4 Test `ProgressBubble`, `VerdictDisplay`, `CitationTable` rendering and data mapping

## 14. Integration Tests

- [ ] 14.1 Test full flow with mock API: submit claim -> SSE events -> verdict display
- [ ] 14.2 Test frozen session revisit: load with frozen session ID -> snapshot iframe
