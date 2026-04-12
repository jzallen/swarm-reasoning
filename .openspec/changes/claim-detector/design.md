## Context

The claim-detector runs in Phase 1 (sequential ingestion phase), immediately after the ingestion agent completes. The `ClaimVerificationWorkflow` dispatches it as a Temporal activity via `workflow.execute_activity()`. The agent reads `CLAIM_TEXT` from the ingestion-agent's Redis stream, scores it, normalizes it, and publishes two observations to its own stream (`reasoning:{runId}:claim-detector`).

Key ADR constraints:
- **ADR-016**: Agent is a Temporal activity worker in the shared agent-service container. No per-agent MCP server or container.
- **ADR-004**: Tool layer constructs all observations; Claude never emits raw JSON
- **ADR-005**: `CHECK_WORTHY_SCORE` starts as `P` (hypothesis during LLM reasoning), promoted to `F` once confirmed; `CLAIM_NORMALIZED` is emitted directly as `F`
- **ADR-003**: Append-only stream -- no corrections expected at this phase; if re-invoked, a new `C`-status observation is published
- **ADR-012**: `ReasoningStream` interface used for all stream I/O; Redis backend in dev

The check-worthiness threshold (0.4) is a hard gate. It is not configurable at runtime -- it is a system constant encoded in the agent. Scores in [0.0, 0.40) are non-check-worthy; scores in [0.40, 1.0] proceed. The normalization step runs unconditionally before the threshold is evaluated: the workflow receives `CLAIM_NORMALIZED` even for cancelled runs, which is useful for deduplication and audit.

## Goals / Non-Goals

**Goals:**
- Implement ClaimBuster-style LLM scoring with a structured prompt that elicits a numeric score and brief rationale
- Publish `P` score during reasoning, upgrade to `F` upon confirmation -- demonstrating ADR-005 status lifecycle
- Apply 0.4 threshold gate and communicate outcome via `finalStatus` in STOP message and activity return value
- Produce a normalized claim form that strips epistemic hedges and resolves pronouns using ingestion-agent context
- Run as a Temporal activity within the shared agent-service container
- Publish progress events for frontend visibility
- Structured test coverage for threshold edge cases (0.39 -> cancel, 0.40 -> proceed, 1.0 -> proceed)

**Non-Goals:**
- Integration with external ClaimBuster API (Claude is the scorer)
- Persistence of the score or normalized text outside Redis Streams
- Multi-claim batching (one run = one claim)
- Dynamic threshold configuration (0.4 is a constant)
- Parallel scoring of multiple claims (Phase 1 is sequential by design)
- Per-agent Dockerfile or docker-compose entry (runs in shared container per ADR-0016)

## Decisions

### 1. Normalization before scoring (not after)

Normalization runs first because the scoring prompt should evaluate the normalized form -- hedging language can inflate check-worthiness scores for claims that are actually opinions dressed up with weasel words. Running normalization first ensures the score reflects the canonical claim.

**Alternative considered:** Score raw text, normalize after. Rejected -- hedging phrases like "reportedly" or "allegedly" may mislead the scorer.

### 2. `P` then `F` status lifecycle for CHECK_WORTHY_SCORE

The agent publishes `CHECK_WORTHY_SCORE` with `P` status immediately after the LLM returns a score, then publishes again with `F` after self-consistency check (a second LLM call or rule-based validation). This demonstrates ADR-005 in a concrete way.

```
OBS{seq:1, code:CLAIM_NORMALIZED, status:F}        -- normalization complete
OBS{seq:2, code:CHECK_WORTHY_SCORE, value:"0.82", status:P}   -- LLM score
OBS{seq:3, code:CHECK_WORTHY_SCORE, value:"0.82", status:F}   -- confirmed
STOP{finalStatus:"F", observationCount:3}
```

For cancelled runs (score < 0.4):
```
OBS{seq:1, code:CLAIM_NORMALIZED, status:F}
OBS{seq:2, code:CHECK_WORTHY_SCORE, value:"0.31", status:P}
OBS{seq:3, code:CHECK_WORTHY_SCORE, value:"0.31", status:F}
STOP{finalStatus:"X", observationCount:3}
```

### 3. Structured scoring prompt with chain-of-thought

The LLM prompt asks Claude to reason step-by-step about check-worthiness before producing a JSON-formatted score. This improves score reliability on borderline claims (0.3-0.5 range) and produces a rationale stored in the observation `note` field.

### 4. Entity reference resolution using ingestion observations

`CLAIM_NORMALIZED` must resolve pronouns and demonstrative references using entity context from the ingestion agent's stream. The `normalize_claim` tool reads `ENTITY_PERSON`, `ENTITY_ORG` observations from the ingestion stream before normalization. If no entity observations are available, pronouns are left unresolved.

### 5. Agent handler with two internal tools

```python
class ClaimDetectorHandler:
    async def run(self, run_id: str) -> AgentResult:
        """Called by run_agent_activity. Normalizes, scores, publishes, returns result."""
```

The handler calls `normalize_claim_text()` (pure function, no LLM) then `score_claim_text()` (Claude LLM call). The Temporal activity wraps the handler and manages heartbeating.

### 6. Package structure (within shared agent-service)

```
services/
  agent-service/
    src/
      agents/
        claim_detector/
          __init__.py
          handler.py       -- ClaimDetectorHandler: run() entry point
          normalizer.py    -- normalize_claim_text(): hedge removal, lowercasing, pronoun resolution
          scorer.py        -- score_claim_text(): Claude LLM call, structured JSON extraction
          prompts.py       -- Scoring prompt template
    tests/
      unit/
        agents/
          test_normalizer.py   -- hedge removal, lowercasing, edge cases
          test_scorer.py       -- score parsing, threshold logic
      integration/
        agents/
          test_claim_detector.py -- Temporal activity end-to-end with live Redis, mocked Claude
```

No per-agent Dockerfile. No per-agent docker-compose entry. The agent runs within the shared `agent-service` container.

### 7. Progress events

The agent publishes progress events to `progress:{runId}`:
- `"Normalizing claim text..."` -- at start
- `"Scoring check-worthiness..."` -- before LLM call
- `"Check-worthiness score: {score} (threshold: 0.4)"` -- after scoring
- `"Claim is check-worthy, proceeding to analysis"` or `"Claim is not check-worthy (score {score} < 0.4), cancelling run"` -- after gate decision

## Risks / Trade-offs

- **[LLM score variability]** -- Claude's score for borderline claims (0.35-0.45) may vary across calls. Mitigated by the `P` -> `F` two-call pattern and a deterministic rule: if `|score1 - score2| > 0.1`, use the lower score (conservative gate).
- **[Pronoun resolution without entity-extractor]** -- entity-extractor runs after claim-detector; we can only use ingestion-agent's signals. Incomplete resolution is logged in the observation `note` field.
- **[Cold Redis start]** -- If the ingestion-agent stream is unavailable, the tool raises `StreamNotFound` and the Temporal activity retries.
- **[Score gaming via hedging injection]** -- Adversarial claim text with many hedging phrases is normalized before scoring, reducing the attack surface.
