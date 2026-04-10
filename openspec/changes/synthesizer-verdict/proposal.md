## Why

Phases 1-3 established the wire format, orchestrator, ingestion pipeline, and all ten upstream agents (including source-validator per ADR-0021). Every agent now publishes observations to Redis Streams, but those observations are raw findings -- uncombined, potentially contradictory, and not yet mapped to a verdict a consumer can act on. Without this slice, the fact-checking system produces no output: claims enter, agents reason, and nothing comes out the other side.

The synthesizer is the only agent that reads the complete multi-agent observation log and produces a single, authoritative verdict. It is the final agent in Phase 3 of the execution DAG. Confidence-scored verdicts tied to PolitiFact's six-tier rating system are the core deliverable of the product; this slice creates them.

This slice also satisfies NFR-019 (swarm verdict accuracy >= 70% on PolitiFact corpus) and NFR-021 (SYNTHESIS_SIGNAL_COUNT must exactly match the count of F/C observations consumed).

## What Changes

- Implement the `synthesizer` agent as a Temporal activity worker in the shared agent-service container (ADR-0016) with four capabilities: observation resolution, confidence scoring, verdict mapping, and narrative generation
- Implement `observation-resolution`: reads all 10 upstream agent streams for a run, applies epistemic precedence rules (C > F, X excluded, P excluded), and emits a consolidated canonical observation set
- Implement `confidence-scoring`: weighted computation over resolved upstream signals using domain evidence alignment, coverage framing, ClaimReview match, cross-spectrum corroboration, blindspot penalty, and SOURCE_CONVERGENCE_SCORE (per ADR-0021: "convergence is a strong signal for confidence scoring")
- Implement `verdict-mapping`: deterministic threshold mapping from CONFIDENCE_SCORE float to PolitiFact six-tier coded verdict using updated thresholds (per docs/domain/entities/verdict.md), plus ClaimReview override logic with SYNTHESIS_OVERRIDE_REASON
- Implement `verdict-narrative`: LLM-generated narrative citing resolved observations by OBX sequence number, with annotated source citations from CITATION_LIST, minimum 200 characters, maximum 1000 characters
- Publish five F-status OBX observations to `reasoning:{runId}:synthesizer` and a STOP message with `finalStatus: "F"`
- Publish progress events to `progress:{runId}` for SSE relay
- Trigger run state transition from ANALYZING to completed via the Temporal workflow completion

## Capabilities

### New Capabilities

- `observation-resolution`: Consolidates 60-80 upstream observations across all 10 agent streams into a single canonical observation set by applying epistemic precedence rules defined in ADR-003 and ADR-005. Produces the resolved input set and SYNTHESIS_SIGNAL_COUNT.
- `confidence-scoring`: Computes a float CONFIDENCE_SCORE in [0.0, 1.0] by applying a weighted signal model over resolved upstream observations, incorporating SOURCE_CONVERGENCE_SCORE as a confidence amplifier. Emits CONFIDENCE_SCORE as an F-status OBX.
- `verdict-mapping`: Maps CONFIDENCE_SCORE to one of seven verdict codes (TRUE, MOSTLY_TRUE, HALF_TRUE, MOSTLY_FALSE, FALSE, PANTS_FIRE, UNVERIFIABLE) using threshold ranges from docs/domain/entities/verdict.md. Applies ClaimReview override when CLAIMREVIEW_MATCH is TRUE and match score is high. Emits VERDICT and SYNTHESIS_OVERRIDE_REASON as F-status OBX rows.
- `verdict-narrative`: Generates a human-readable explanation of the verdict, referencing specific upstream findings by OBX sequence number and annotating with source citations from CITATION_LIST. Emits VERDICT_NARRATIVE as an F-status OBX with length 200-1000 characters.

### Modified Capabilities

- `run-lifecycle` (orchestrator-core): The orchestrator Temporal workflow transitions the run to completed when the synthesizer activity completes successfully.

## Impact

- **New package**: `src/swarm_reasoning/agents/synthesizer/` (Python)
- **No new containers**: Agent runs as a Temporal activity worker in the shared agent-service container (ADR-0016)
- **Dependencies**: `anthropic` Python SDK (narrative generation), existing `ReasoningStream` interface, `ObservationResolver` from this slice
- **Consumer API** depends on: VERDICT, CONFIDENCE_SCORE, VERDICT_NARRATIVE, SYNTHESIS_SIGNAL_COUNT, SYNTHESIS_OVERRIDE_REASON OBX codes, plus CITATION_LIST from source-validator
- **Validation harness** depends on: synthesizer STOP message structure and completed run state transition
- **Gherkin coverage**: `verdict-synthesis.feature` (13 scenarios) and `verdict-publication.feature` (12 scenarios, partially; publication delivery is a separate slice)
