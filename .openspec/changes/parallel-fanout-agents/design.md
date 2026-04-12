## Context

Phase 2 of the swarm-reasoning execution DAG is a parallel fan-out: the orchestrator Temporal workflow dispatches six agent activities concurrently after Phase 1 (ingestion + claim-detection + entity-extraction) completes. Each agent is a Temporal activity worker running in the shared agent-service container. The orchestrator workflow starts all six activities in parallel and awaits their completion via Temporal's native activity result handling. Agents read upstream context from Redis Streams (CLAIM_NORMALIZED, ENTITY_* codes) and write their results to their own stream.

The six Phase 2 agents are:
1. `claimreview-matcher` -- Google Fact Check Tools API lookup
2. `coverage-left` -- Left-spectrum NewsAPI coverage analysis
3. `coverage-center` -- Center-spectrum NewsAPI coverage analysis
4. `coverage-right` -- Right-spectrum NewsAPI coverage analysis
5. `domain-evidence` -- Authoritative domain source research
6. `source-validator` -- Link extraction, URL validation, source convergence, citation aggregation (detailed in its own slice)

Key constraints from ADRs and NFRs:
- ADR-0016: Temporal.io orchestration -- each agent is a Temporal activity; the orchestrator is a Temporal workflow. No MCP servers, no per-agent containers
- ADR-0004: Tool-based observation construction -- LLMs never generate raw observations; a `publish_observation` tool enforces schema validity at write time
- ADR-0011: JSON observation schema -- all observations are JSON per the stream message spec
- ADR-0003: Append-only observation log -- agents only XADD; no corrections or deletions in Phase 2
- ADR-0012: ReasoningStream interface -- agents use the abstract transport interface backed by Redis in dev
- ADR-0013: Two communication planes -- Temporal control plane + Redis Streams data plane
- NFR-002: Phase 2a wall-clock latency <= 45 seconds (five agents in parallel; source-validator runs sequentially in Phase 2b)
- NFR-012: All external API calls must return HTTP 200 or 3xx; 4xx/5xx responses trigger a graceful no-result observation (status X) rather than a run failure

## Goals / Non-Goals

**Goals:**
- Implement five Phase 2 agents as Temporal activity workers (claimreview-matcher, 3 coverage agents, domain-evidence) with shared base class
- Acknowledge source-validator as the 6th Phase 2 agent (implemented in its own slice)
- Each agent reads upstream context (normalized claim, entities) from Redis Streams at startup
- Each agent calls its external API, processes results, and publishes typed observations to Redis Streams
- Each agent publishes progress events to `progress:{runId}` for SSE relay to the frontend
- Handle external API failures gracefully (publish X-status STOP, not unhandled exceptions)
- Each agent completes within the 45-second NFR-002 budget (target: <= 20s per agent, leaving margin)

**Non-Goals:**
- Inter-agent communication or result sharing during Phase 2 (agents are fully independent)
- Retry logic beyond a single configurable retry for transient HTTP failures (Temporal handles activity-level retries per ADR-0016)
- Semantic similarity model hosting (ClaimReview match scoring uses TF-IDF cosine similarity; no GPU inference)
- NewsAPI source credibility database management (static JSON fixture per spectrum; updates are out of scope)
- Domain routing for all possible CLAIM_DOMAIN values in the first slice (MVP covers HEALTHCARE, ECONOMICS, POLICY, SCIENCE; OTHER falls back to web search)
- Source-validator implementation (separate slice per ADR-0021)

## Decisions

### 1. FanoutActivity shared base class

All five Phase 2a agents (plus source-validator in Phase 2b) share a common `FanoutActivity` base class that handles: stream key resolution, upstream context loading (reads CLAIM_NORMALIZED and ENTITY_* from Redis at start), START/STOP message emission, progress event publishing, and the `publish_observation` tool. Individual agent classes override `_execute()` to contain agent-specific logic.

The base class is a Temporal activity that:
1. Receives `run_id` and `claim_id` as activity input from the orchestrator workflow
2. Loads upstream context from Redis Streams via the ReasoningStream interface
3. Publishes a START message to the agent's stream
4. Calls the subclass `_execute()` method
5. Publishes a STOP message with finalStatus and observationCount
6. Returns a completion result to the Temporal workflow

**Alternative considered:** Duplicate the base logic in each agent. Rejected -- six agents with identical scaffolding would diverge quickly; a base class is the right factoring.

### 2. ClaimReview match scoring with cosine similarity

The Google Fact Check Tools API returns a list of ClaimReview entries. Match scoring uses cosine similarity over TF-IDF vectors of the submitted normalized claim vs. the `claimReviewed` text from each result. The highest-scoring match above 0.75 threshold is selected; below 0.75 is flagged as an uncertain match (score is still published, but CLAIMREVIEW_MATCH remains TRUE so the synthesizer can apply its own threshold). Below 0.5 is treated as no match.

```
match_score = cosine_similarity(tfidf(claim_normalized), tfidf(claimReviewed))
```

**Alternative considered:** Embedding model (sentence-transformers). Rejected for MVP -- adds inference latency and a model download to startup. TF-IDF is deterministic, requires no model weights, and is sufficient for substring/keyword overlap matching.

### 3. Coverage spectrum source lists as static fixtures

Left, center, and right source lists are maintained as static JSON fixtures in `src/swarm_reasoning/agents/coverage_*/sources.json`. Each list contains NewsAPI `sources` parameter values (e.g. `"huffington-post,msnbc,the-nation"` for left). Framing detection runs VADER SentimentIntensityAnalyzer over the top 5 articles returned.

**Alternative considered:** Dynamic source credibility API (AllSides, MediaBiasFactCheck). Rejected -- external dependency on a non-free API; static fixtures are sufficient for MVP and reviewable by humans.

### 4. Domain-evidence routing table

A static routing table maps CLAIM_DOMAIN values to a prioritized list of base URLs and search URL templates. The agent selects the first source that returns HTTP 200 with relevant content (heuristic: title/heading contains at least one claim entity).

```python
DOMAIN_ROUTES = {
    "HEALTHCARE": ["https://www.cdc.gov/search/?query={query}", "https://www.who.int/search?query={query}"],
    "ECONOMICS":  ["https://efts.sec.gov/LATEST/search-index?q={query}", "https://fred.stlouisfed.org/..."],
    "POLICY":     ["https://www.congress.gov/search?query={query}", "https://www.govinfo.gov/..."],
    "SCIENCE":    ["https://pubmed.ncbi.nlm.nih.gov/?term={query}", "https://scholar.google.com/..."],
    "OTHER":      ["https://www.google.com/search?q={query}+site:gov+OR+site:edu"],
}
```

**Alternative considered:** LLM-driven source selection. Rejected -- non-deterministic, slower, and adds an LLM call per evidence lookup. The routing table is transparent and testable.

### 5. Agent package structure

```
src/
  swarm_reasoning/
    agents/
      fanout_base.py                 -- FanoutActivity ABC: context loading, START/STOP, publish_observation, progress events
      claimreview_matcher/
        __init__.py
        activity.py                  -- ClaimReviewMatcherActivity: Google API call, match scoring
      coverage_left/
        __init__.py
        activity.py                  -- CoverageActivity(spectrum="left")
        sources.json                 -- Left-spectrum NewsAPI source list
      coverage_center/
        __init__.py
        activity.py                  -- CoverageActivity(spectrum="center")
        sources.json                 -- Center-spectrum NewsAPI source list
      coverage_right/
        __init__.py
        activity.py                  -- CoverageActivity(spectrum="right")
        sources.json                 -- Right-spectrum NewsAPI source list
      domain_evidence/
        __init__.py
        activity.py                  -- DomainEvidenceActivity: domain routing, alignment scoring
        routes.json                  -- CLAIM_DOMAIN -> source URL template mapping
      coverage_core.py               -- Shared coverage logic: query building, framing detection, source selection
tests/
  unit/
    agents/
      test_fanout_base.py
      test_claimreview_matcher.py
      test_coverage_agent.py
      test_domain_evidence.py
  integration/
    agents/
      test_fanout_phase.py           -- Full Phase 2 mock: all six agents, Temporal workflow
```

### 6. Temporal activity interface

Each agent registers as a Temporal activity:

```python
@activity.defn
async def run_claimreview_matcher(input: FanoutActivityInput) -> FanoutActivityResult:
    """Execute ClaimReview matcher for the given run and claim."""
    agent = ClaimReviewMatcherActivity(input)
    return await agent.run()
```

The activity input (`FanoutActivityInput`) contains `run_id`, `claim_id`, and optionally `cross_agent_data` (used by source-validator to receive other agents' observations). The result (`FanoutActivityResult`) contains `status` ("COMPLETED" or "CANCELLED"), `observation_count`, and `error_reason` (if cancelled).

The orchestrator workflow dispatches the five Phase 2a activities concurrently. Source-validator runs in Phase 2b after 2a completes (see orchestrator-core DAG):

```python
# Phase 2a: five evidence-gathering agents in parallel
results_2a = await asyncio.gather(
    workflow.execute_activity(run_claimreview_matcher, input, ...),
    workflow.execute_activity(run_coverage_left, input, ...),
    workflow.execute_activity(run_coverage_center, input, ...),
    workflow.execute_activity(run_coverage_right, input, ...),
    workflow.execute_activity(run_domain_evidence, input, ...),
)
# Phase 2b: source-validator with cross-agent data from 2a
result_2b = await workflow.execute_activity(run_source_validator, input_with_cross_data, ...)
```

### 7. Progress event publishing

Each agent publishes user-friendly progress events to `progress:{runId}` via the ReasoningStream interface. Events include agent start, key findings, and completion. These are relayed to the frontend via SSE (ADR-0018).

```python
await self.stream.publish_progress(run_id, {
    "agent": self.agent_name,
    "event": "started",
    "message": f"{self.agent_name} is analyzing the claim..."
})
```

## Risks / Trade-offs

- **[Google Fact Check Tools API rate limits]** -> 100 requests/day on free tier. Add a `CLAIMREVIEW_API_QUOTA_REMAINING` log metric. If quota is exhausted, publish CLAIMREVIEW_MATCH = FALSE with a note. Accept this for dev/test workloads.
- **[NewsAPI free tier: 100 requests/day, no source filtering on free plan]** -> Use mock responses in integration tests. Production requires a paid NewsAPI plan.
- **[Domain-evidence web scraping fragility]** -> Source URLs may change or return paywalled content. Mitigate with a content-check heuristic; fall back to DOMAIN_EVIDENCE_ALIGNMENT = ABSENT rather than failing.
- **[TF-IDF match scoring non-determinism across tokenizers]** -> Use `sklearn.feature_extraction.text.TfidfVectorizer` with a fixed vocabulary for reproducibility. Pin sklearn version.
- **[NFR-002: 45s budget for Phase 2a]** -> Parallel execution means the budget is determined by the slowest of the five agents. Target <= 20s per agent. Source-validator adds sequential time in Phase 2b. If ClaimReview or NewsAPI responses are slow, the 45s limit is at risk. Temporal activity timeout set to 45s per activity.
- **[Temporal activity timeout vs. agent timeout]** -> The Temporal activity-level timeout (45s) is the hard boundary. The agent's internal timeout (30s) provides an earlier graceful degradation path. If the internal timeout fires, the agent publishes X-status and returns normally. If the Temporal timeout fires, the activity is cancelled.
