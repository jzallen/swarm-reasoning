## Why

Phase 1 (ingestion-agent, claim-detector, entity-extractor) produces normalized claim text, typed entities, and a check-worthiness gate. Without the six parallel fanout agents, no external evidence is gathered and the synthesizer has nothing to score. These agents are the primary evidence-collection layer of the system -- they run concurrently as Temporal activities in Phase 2 and their output directly determines verdict confidence. This slice must exist before the synthesizer because it defines the upstream signal set the synthesizer depends on.

## What Changes

- Implement `claimreview-matcher`: Google Fact Check Tools API integration using entity + normalized claim as search terms, semantic match scoring, and 5-observation output (CLAIMREVIEW_MATCH, CLAIMREVIEW_VERDICT, CLAIMREVIEW_SOURCE, CLAIMREVIEW_URL, CLAIMREVIEW_MATCH_SCORE)
- Implement `coverage-left`, `coverage-center`, `coverage-right`: Three parallel NewsAPI agents each querying a spectrum-specific source list, detecting framing via VADER sentiment, and emitting 4 observations each (COVERAGE_ARTICLE_COUNT, COVERAGE_FRAMING, COVERAGE_TOP_SOURCE, COVERAGE_TOP_SOURCE_URL)
- Implement `domain-evidence`: Primary source evidence research against authoritative domain sources, alignment scoring, and 4-observation output (DOMAIN_SOURCE_NAME, DOMAIN_SOURCE_URL, DOMAIN_EVIDENCE_ALIGNMENT, DOMAIN_CONFIDENCE)
- Reference `source-validator` as Phase 2b (detailed spec in its own slice). This slice covers the five Phase 2a agents that run in parallel; source-validator runs sequentially after 2a completes (per orchestrator-core DAG)
- Each agent runs as a Temporal activity worker in the shared agent-service container (ADR-0016). No per-agent MCP servers or containers
- All five Phase 2a agents write to independent stream keys via the ReasoningStream interface -- no cross-agent coordination required
- The orchestrator Temporal workflow dispatches all five Phase 2a activities concurrently and awaits their completion before dispatching source-validator in Phase 2b

## Capabilities

### New Capabilities

- `claimreview-lookup`: Google Fact Check Tools API integration. Accepts normalized claim text and entity list from the stream, performs keyword + semantic search, scores match quality (0.0-1.0), and publishes 5 CLAIMREVIEW_* observations. Handles no-match case gracefully (CLAIMREVIEW_MATCH = FALSE, score = 0.0, remaining codes omitted or marked X).
- `coverage-analysis`: Three-spectrum news coverage analysis via NewsAPI. Left, center, and right coverage agents each query NewsAPI with claim-derived search terms filtered to their spectrum's source list. Each agent detects framing (SUPPORTIVE/CRITICAL/NEUTRAL/ABSENT) and identifies the top credibility-ranked source. The three agents run in parallel with no inter-agent dependencies; each writes 4 observations to its own stream.
- `domain-evidence-research`: Primary source evidence gathering for domain-specific claims. Routes to appropriate authoritative sources based on CLAIM_DOMAIN (e.g. CDC/WHO for HEALTHCARE, SEC/EDGAR for ECONOMICS, court records for POLICY). Scores alignment (SUPPORTS/CONTRADICTS/PARTIAL/ABSENT) and confidence (penalized for indirect, dated, or ambiguous sources). Publishes 4 DOMAIN_* observations.

### Modified Capabilities

- `redis-infrastructure` (slice 1): No structural changes. Six new stream keys created at runtime (`reasoning:{runId}:claimreview-matcher`, `reasoning:{runId}:coverage-left`, `reasoning:{runId}:coverage-center`, `reasoning:{runId}:coverage-right`, `reasoning:{runId}:domain-evidence`, `reasoning:{runId}:source-validator`). Consumed by the orchestrator workflow completion logic.

## Impact

- **New packages**: `src/swarm_reasoning/agents/claimreview_matcher/`, `src/swarm_reasoning/agents/coverage_left/`, `src/swarm_reasoning/agents/coverage_center/`, `src/swarm_reasoning/agents/coverage_right/`, `src/swarm_reasoning/agents/domain_evidence/`
- **Shared base**: `src/swarm_reasoning/agents/fanout_base.py` -- `FanoutActivity` base class shared by all Phase 2 agents (5 in Phase 2a + source-validator in Phase 2b)
- **No new containers**: All agents run as Temporal activity workers in the shared agent-service container (ADR-0016)
- **External dependencies**: `GOOGLE_FACTCHECK_API_KEY` (ClaimReview), `NEWSAPI_KEY` (coverage agents); `httpx` for async HTTP
- **Slice dependencies**: Reads CLAIM_NORMALIZED (claim-detector) and ENTITY_* observations (entity-extractor) from Redis Streams before starting
- **Downstream impact**: Synthesizer reads F-status observations from all six streams; blindspot-detector reads all three COVERAGE_FRAMING observations; source-validator reads URL observations from all agents
- **NFR-002**: Phase 2a wall-clock time <= 45 seconds with five agents running in parallel; source-validator runs sequentially in Phase 2b
