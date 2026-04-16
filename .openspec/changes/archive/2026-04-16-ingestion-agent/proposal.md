## Why

Slice 1 (redis-streams-observation-schema) established the observation type system and `ReasoningStream` interface. The ingestion agent is the entry point for every fact-checking run -- no claim can progress to parallel fanout until ingestion completes and its four `CLAIM_*` observations are written. Without ingestion-agent, the pipeline cannot start.

The ingestion agent has a second distinct responsibility: it gates non-check-worthy claims before downstream agents waste resources. It must validate that submitted text is factual and specific enough to fact-check, then classify it by domain so downstream agents can prioritize the correct sources.

## What Changes

- Implement the `ingestion-agent` as a Temporal activity worker within the shared Python agent-service container (ADR-0016)
- The agent exposes two LangChain tools (`ingest_claim` and `classify_domain`) that are invoked within the Temporal activity execution
- Implement claim validation logic: URL format check, date format normalization (ISO 8601 -> YYYYMMDD), text length guard (5-2000 chars), duplicate detection via run-scoped Redis key
- Implement domain classification: send claim text to Claude claude-sonnet-4-6, parse response against the controlled vocabulary (HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER), retry once on ambiguous output
- On successful intake, publish four observations to the run's Redis Stream: `CLAIM_TEXT`, `CLAIM_SOURCE_URL`, `CLAIM_SOURCE_DATE` (status `F`), and `CLAIM_DOMAIN` (status `P` after classification, promoted to `F` after LLM confirmation)
- Publish progress events to `progress:{runId}` stream for SSE relay to frontend
- Stream lifecycle: agent opens with `START`, publishes observations via the tool layer, closes with `STOP finalStatus=F`; if validation fails, closes with `STOP finalStatus=X`

## Capabilities

### New Capabilities

- `claim-intake`: LangChain tool that accepts a raw claim submission, performs structural validation and metadata extraction, and publishes `CLAIM_TEXT`, `CLAIM_SOURCE_URL`, and `CLAIM_SOURCE_DATE` observations to the run's Redis Stream
- `domain-classification`: LLM-powered LangChain tool that calls Claude to assign the claim to a domain from the controlled vocabulary and publishes a `CLAIM_DOMAIN` observation

### Modified Capabilities

None -- this is a new agent with no prior implementation.

## Impact

- **New module**: `services/agent-service/src/agents/ingestion_agent/` (Python, within the shared agent-service container)
- **Temporal activity**: registered as `ingestion-agent` activity in the agent-service worker; the `ClaimVerificationWorkflow` dispatches it as the first activity in Phase 1
- **No per-agent container**: runs in the shared agent-service container alongside all other agent workers (ADR-0016)
- **Stream output**: produces four `CLAIM_*` observations per run using the `ReasoningStream` interface from slice 1
- **Progress output**: publishes user-friendly progress events to `progress:{runId}` for SSE relay
- **Depends on**: `swarm_reasoning` package (slice 1) for `Observation`, `ReasoningStream`, `ObservationCode`, `EpistemicStatus`
- **Downstream unblocked**: claim-detector, entity-extractor, and all fanout agents depend on `CLAIM_TEXT` being present in the stream before they can operate
