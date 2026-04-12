## Context

ADR-0014 specifies a React/TypeScript SPA built with Vite as the frontend service. The frontend communicates exclusively with the NestJS backend API -- it never contacts the agent service directly. The API surface is defined in `docs/api/openapi.yaml`: session creation, claim submission, SSE progress streaming, verdict retrieval, and session status.

Key constraints from architecture docs:
- ADR-0014: Three-service architecture -- frontend is a static SPA deployed to S3+CloudFront in production
- ADR-0018: SSE relay -- frontend uses native `EventSource` API to receive progress events
- ADR-0019: Static HTML snapshots -- frozen sessions display the snapshot, not the live SPA
- Session entity: UUID v4, states `active` / `frozen` / `expired`, 3-day TTL
- Verdict entity: factuality score (0.0-1.0), rating label (PolitiFact scale), narrative, citations
- ProgressEvent entity: types `agent-started`, `agent-progress`, `agent-completed`, `verdict-ready`, `session-frozen`
- No authentication, no login, no user accounts
- Session ID in URL path: `/{sessionId}`

## Goals / Non-Goals

**Goals:**
- Scaffold a complete React/TypeScript SPA with Vite
- Implement claim submission with session lifecycle (create session -> submit claim -> stream progress -> show verdict)
- Integrate native `EventSource` for real-time SSE progress
- Render progress messages as a chat-style conversation log
- Render the verdict with factuality score, rating badge, narrative, and citation table
- Handle frozen sessions by displaying the static HTML snapshot
- Responsive design for desktop and mobile
- Print button for saving results

**Non-Goals:**
- Server-side rendering (ADR-0014 explicitly chose client-side SPA)
- Authentication or user accounts (ADR-0019: no login)
- Client-side routing library (single-page with session ID in URL, no need for React Router)
- State management library (React useState/useReducer is sufficient for single-session state)
- Component library (custom components, no Material UI or similar)
- Offline support or service worker
- Internationalization

## Decisions

### 1. Vite with React and TypeScript, no additional framework

Vite provides fast HMR, TypeScript support, and optimized production builds. No additional meta-framework (Next.js, Remix) is needed because the app is a client-side SPA with no SSR. No routing library is needed because there is only one page, parameterized by the session ID in the URL path.

**Alternative considered:** Next.js. Rejected -- SSR adds complexity and a server runtime; the app is a static SPA deployed to S3.

### 2. Session ID in URL via `window.history.pushState`

When a session is created, the URL is updated to `/{sessionId}` using `pushState`. On page load, the app checks `window.location.pathname` for a session ID. If present, it fetches the session status. If absent, it shows the landing page with the claim input.

**Alternative considered:** Query parameter (`?session=abc`). Rejected -- path-based URLs are cleaner for sharing and bookmarking.

### 3. EventSource with custom reconnection hook

A custom React hook `useSSE(sessionId)` wraps the native `EventSource` API. It:
- Opens a connection to `GET /sessions/:id/events`
- Listens for `progress`, `verdict`, and `close` event types
- Dispatches parsed events to a React `useReducer` state
- Handles `EventSource.onerror` by relying on native auto-reconnect (which sends `Last-Event-ID`)
- Closes the connection when a `close` event is received or the component unmounts

**Alternative considered:** Third-party SSE library. Rejected -- the native `EventSource` API provides everything needed, including auto-reconnect.

### 4. Chat-style progress display with agent avatars

Progress messages are rendered as chat bubbles in a scrolling container. Each bubble shows the agent name as a label, a phase badge (ingestion/fanout/synthesis), the message text, and a timestamp. New messages auto-scroll to the bottom. The chat area is the primary interface during active sessions.

**Alternative considered:** Timeline/stepper UI. Rejected -- chat-style is more engaging and matches the "conversation with agents" metaphor.

### 5. Verdict display as a composite card

The verdict is rendered as a card with:
- Factuality score as a large KPI number (0.00 - 1.00)
- Rating label as a color-coded badge (green for True/Mostly True, yellow for Half True, red for Mostly False/False/Pants on Fire)
- Narrative explanation as body text
- Citation table below with columns: source name, URL (linked), discovering agent, observation code, validation status (icon + label), convergence count

**Alternative considered:** Separate verdict page. Rejected -- the verdict should appear in-context below the chat log, maintaining the conversation flow.

### 6. Frozen session revisit via iframe or fetch

When the app detects a session with status `frozen` and a `snapshotUrl`, it fetches the static HTML snapshot and renders it in an iframe (or injects it via `srcdoc`). This avoids re-implementing the verdict display for frozen sessions -- the snapshot is self-contained.

**Alternative considered:** Re-render from API data. Rejected -- the snapshot is the canonical frozen representation (ADR-0019); re-rendering risks divergence.

### 7. No CSS framework, custom styles with CSS modules

The app uses CSS Modules for scoped styling. No CSS framework (Tailwind, Bootstrap) is used. The design is minimal and focused: a centered chat container, responsive breakpoints for mobile, and print-friendly styles via `@media print`. Colors follow the PolitiFact rating scale for the verdict badge.

**Alternative considered:** Tailwind CSS. Rejected -- adds a build dependency for a small app; CSS Modules are sufficient and keep the bundle small.

## Risks / Trade-offs

- **[EventSource browser limits]** HTTP/1.1 limits browsers to ~6 concurrent SSE connections per domain. Mitigation: this is a single-session app; only one SSE connection is open at a time. HTTP/2 eliminates the limit.
- **[Snapshot iframe sandbox]** Embedding the static HTML in an iframe may have CSP or same-origin issues. Mitigation: the snapshot is served from the same origin (or S3 with CORS headers). Use `srcdoc` attribute if same-origin loading is problematic.
- **[No loading skeleton]** During the gap between session creation and first SSE event, the chat area is empty. Mitigation: show a "Connecting to agents..." placeholder message immediately after claim submission.
- **[Mobile responsiveness]** The citation table may overflow on narrow screens. Mitigation: horizontal scroll on the table container, or collapse columns into a stacked card layout on mobile.
