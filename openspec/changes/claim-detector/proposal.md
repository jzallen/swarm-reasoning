## Why

The ingestion agent publishes raw claim text to Redis Streams, but raw text is unsuitable for downstream evidence-gathering agents. Two problems must be solved before fanout can begin: (1) many submitted claims are opinions, satire, or non-factual statements that cannot be fact-checked -- processing them wastes resources and produces meaningless verdicts; (2) raw claim text contains hedging language, ambiguous pronouns, and inconsistent casing that prevents reliable cross-source matching and retrieval.

The claim-detector is the gate between ingestion and analysis. It runs in Phase 1 (sequential, immediately after ingestion) and must complete before the entity-extractor is dispatched. Without it, the system has no check-worthiness gate and no normalized form of the claim -- both of which downstream agents depend on.

## What Changes

- Implement the `claim-detector` as a Temporal activity worker within the shared Python agent-service container (ADR-0016)
- The agent exposes two LangChain tools invoked within the Temporal activity execution
- Implement `check-worthiness` scoring via Claude LLM using a ClaimBuster-style prompt -- output is `CHECK_WORTHY_SCORE` (NM, 0.0-1.0) published to Redis Streams
- Implement the 0.4 threshold gate: scores below 0.4 trigger a `STOP` with `finalStatus = "X"`, signaling the workflow to cancel the run; scores >= 0.4 emit `finalStatus = "F"` and allow the workflow to proceed
- Implement `claim-normalization` -- lowercasing, hedging language removal, and entity reference resolution -- producing `CLAIM_NORMALIZED` (ST) published to Redis Streams
- Both OBX codes (`CHECK_WORTHY_SCORE`, `CLAIM_NORMALIZED`) are owned by `claim-detector` per `docs/domain/obx-code-registry.json`
- Observations are published via the `ReasoningStream` interface (slice 1) using the tool layer (ADR-004); Claude never constructs raw observation JSON
- Publish progress events to `progress:{runId}` for SSE relay to the frontend

## Capabilities

### New Capabilities

- `check-worthiness`: ClaimBuster-style check-worthiness scoring via Claude. Reads `CLAIM_TEXT` from the ingestion-agent's stream, scores 0.0-1.0, publishes `CHECK_WORTHY_SCORE` with `P` then `F` status, applies 0.4 threshold gate to cancel or proceed the run.
- `claim-normalization`: Text normalization pipeline. Lowercases the claim, removes hedging phrases (reportedly, allegedly, sources say, etc.), resolves pronoun/demonstrative references using entity context from the ingestion stream. Publishes `CLAIM_NORMALIZED` with `F` status.

### Modified Capabilities

None -- this is a new agent with no existing implementation.

## Impact

- **New module**: `services/agent-service/src/agents/claim_detector/` (Python, within shared agent-service container)
- **Temporal activity**: registered as `claim-detector` activity in the agent-service worker; dispatched by `ClaimVerificationWorkflow` as the second activity in Phase 1
- **No per-agent container**: runs in the shared agent-service container alongside all other agent workers (ADR-0016)
- **Dependencies**: `anthropic` SDK (Claude LLM), `swarm_reasoning` types package (slice 1)
- **Upstream dependency**: Reads from `reasoning:{runId}:ingestion-agent` stream
- **Downstream consumers**: workflow reads `terminal_status` to gate fanout; entity-extractor and all fanout agents consume `CLAIM_NORMALIZED` as input
- **Run cancellation path**: When score < 0.4, the agent returns `terminal_status="X"` and the workflow cancels the run
- **Gherkin coverage**: Scenarios "Check-worthy claim proceeds to ANALYZING", "Below-threshold claim is cancelled", and "Claim detector publishes normalized claim text" in `docs/features/claim-ingestion.feature`
