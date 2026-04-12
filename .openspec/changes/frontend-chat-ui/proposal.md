## Why

The system has a NestJS backend API, an agent service, and SSE progress relay, but no user interface. Users need a way to submit claims, watch agents work in real-time, and view annotated verdicts with citations. ADR-0014 specifies a React/TypeScript SPA built with Vite as the frontend service. ADR-0019 specifies that frozen sessions display a static HTML snapshot. This slice delivers the complete frontend: chat interface for claim submission and progress display, SSE client integration for real-time updates, verdict display with factuality score and citation table, and the revisit flow for frozen sessions.

## What Changes

- Scaffold a React/TypeScript SPA with Vite, configured for port 5173
- Implement a landing page with a chat-style interface: text input for claim submission, scrolling message area for progress updates
- Wire session creation (`POST /sessions`) and claim submission (`POST /sessions/:id/claims`) to the backend API
- Integrate `EventSource` to connect to `GET /sessions/:id/events` for real-time SSE progress
- Render agent progress messages as chat bubbles with agent name, phase badge, and timestamp
- Render the verdict as a factuality score KPI card, rating label badge, narrative text, and citation table with validation status indicators
- Implement the revisit flow: if session is `frozen`, fetch and embed the static HTML snapshot instead of the live chat
- Add a print button that triggers `window.print()` for saving results
- Session ID in URL path (`/{sessionId}`), no routing framework needed
- Responsive layout for desktop and mobile
- No authentication, no login

## Capabilities

### New Capabilities

- `chat-interface`: Landing page with claim text input, submit button, and scrolling chat-style message area. On submit, creates a session via `POST /sessions`, updates the URL with the session ID, submits the claim via `POST /sessions/:id/claims`, and begins streaming progress.
- `sse-client`: EventSource wrapper that connects to the backend SSE endpoint, parses `progress`, `verdict`, and `close` event types, dispatches them to React state, and handles reconnection with `Last-Event-ID`.
- `verdict-display`: Renders the final verdict as a KPI card (factuality score 0.0-1.0), color-coded rating label badge (PolitiFact scale), narrative explanation, and a citation table with columns for source name, URL, discovering agent, observation code, validation status icon, and convergence count.

### Modified Capabilities

- None. This is a new slice.

## Impact

- **New directory**: `services/frontend/` -- complete React/TypeScript SPA
- **New files**: Vite config, index.html, App component, ChatInterface component, SSEClient hook, VerdictDisplay component, CitationTable component, ProgressBubble component, API client module, CSS/styles
- **Docker Compose**: The existing `frontend` service definition in `docker-compose.yml` already points to `services/frontend/` and runs `npm run dev` on port 5173
- **No backend changes**: Frontend consumes existing API endpoints defined in `openapi.yaml`
