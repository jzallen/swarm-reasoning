# Capability: check-worthiness

## Purpose

Score a submitted claim on its factual check-worthiness using a ClaimBuster-style methodology implemented via Claude LLM. Apply a 0.4 threshold gate to decide whether the run proceeds to fanout or is cancelled. The agent runs as a Temporal activity worker within the shared agent-service container (ADR-0016).

---

## Inputs

| Source | Field | Type | Description |
|---|---|---|---|
| Redis Stream `reasoning:{runId}:ingestion-agent` | `CLAIM_TEXT` observation | ST | Raw claim text as submitted by the operator |
| Redis Stream `reasoning:{runId}:claim-detector` | `CLAIM_NORMALIZED` observation | ST | Normalized claim text (produced by claim-normalization capability, which runs first) |

The agent reads `CLAIM_NORMALIZED` from its own stream (written by the normalization step) before invoking the scorer. The raw `CLAIM_TEXT` is available for fallback if normalization has not yet been published.

---

## Outputs

### Observation: CHECK_WORTHY_SCORE (preliminary)

```json
{
  "type": "OBS",
  "observation": {
    "runId": "{runId}",
    "agent": "claim-detector",
    "seq": 2,
    "code": "CHECK_WORTHY_SCORE",
    "value": "0.82",
    "valueType": "NM",
    "units": "score",
    "referenceRange": "0.0-1.0",
    "status": "P",
    "timestamp": "2026-04-10T12:00:03Z",
    "method": "score_claim",
    "note": "LLM rationale: claim contains specific verifiable assertion attributed to named federal agency"
  }
}
```

### Observation: CHECK_WORTHY_SCORE (final)

Same structure as above with `"status": "F"` and seq incremented. Published after self-consistency validation.

### STOP message (check-worthy run)

```json
{
  "type": "STOP",
  "runId": "{runId}",
  "agent": "claim-detector",
  "finalStatus": "F",
  "observationCount": 3,
  "timestamp": "2026-04-10T12:00:04Z"
}
```

### STOP message (cancelled run, score < 0.4)

```json
{
  "type": "STOP",
  "runId": "{runId}",
  "agent": "claim-detector",
  "finalStatus": "X",
  "observationCount": 3,
  "timestamp": "2026-04-10T12:00:04Z"
}
```

---

## Scoring Protocol

### Step 1 -- Read normalized claim

Read `CLAIM_NORMALIZED` from `reasoning:{runId}:claim-detector` stream. If not found (normalization failed), fall back to `CLAIM_TEXT` from `reasoning:{runId}:ingestion-agent`. Raise `StreamNotFound` if neither is available.

### Step 2 -- LLM scoring call

Invoke Claude with the structured scoring prompt (see `prompts.py`). Extract `score` (float) and `rationale` (string) from the JSON response.

Scoring prompt criteria applied by Claude:
- Contains a specific, verifiable factual assertion -> +score
- Attributed to a named person, organization, or institution -> +score
- Contains measurable quantities, percentages, or dates -> +score
- Pure opinion, normative judgment, or satire -> score approaches 0.0
- Non-falsifiable statement ("politicians are corrupt") -> score approaches 0.0
- Hedging language (allegedly, reportedly, sources say) -> -score
- Metaphor, hyperbole, or rhetorical question -> score approaches 0.0

### Step 3 -- Publish P-status observation

Publish `CHECK_WORTHY_SCORE` with `status = "P"`, `value = str(score)`, `note = rationale[:512]`.

### Step 4 -- Self-consistency check

Run a second, lightweight confirmation pass. If `|score_pass1 - score_pass2| > 0.1`, use `min(score_pass1, score_pass2)` (conservative gate). Else use `score_pass1`. This is implemented as a single Claude call asking "confirm or revise" with the pass-1 score visible.

### Step 5 -- Publish F-status observation

Publish `CHECK_WORTHY_SCORE` with `status = "F"`, `value = str(final_score)`.

### Step 6 -- Gate decision

```
if final_score >= 0.4:
    publish STOP with finalStatus = "F"
else:
    publish STOP with finalStatus = "X"
```

The Temporal activity returns `AgentActivityResult` with `terminal_status` matching `finalStatus`. The `ClaimVerificationWorkflow` checks this return value and calls `cancel_run` if `terminal_status = "X"`.

---

## Threshold Semantics

| Score Range | Decision | Run Status Transition | Workflow Action |
|---|---|---|---|
| 0.40 - 1.00 | Check-worthy | `ingesting` (continues) | Dispatch entity-extractor |
| 0.00 - 0.39 | Not check-worthy | `ingesting` -> `cancelled` | Cancel run, halt all dispatch |

The threshold value `0.40` is a system constant in `scorer.py`. It is not exposed via configuration.

---

## Temporal Activity Integration

The claim-detector handler is invoked within the `run_agent_activity` Temporal activity. The activity:
1. Looks up the `ClaimDetectorHandler` from the agent registry
2. Calls `handler.run(run_id)`
3. Heartbeats every 10 seconds via `activity.heartbeat()` during LLM calls
4. Returns `AgentActivityResult` with `terminal_status`, `observation_count`, and `duration_ms`

Retry policy: Anthropic rate limits and timeouts are retryable (Temporal retries up to 3 times with exponential backoff). Auth errors and `StreamNotFound` are non-retryable.

---

## Error Conditions

| Condition | Behavior |
|---|---|
| Ingestion stream not found | Raise `StreamNotFound` (non-retryable); Temporal activity fails immediately |
| LLM returns malformed JSON | Retry up to 2 times with temperature = 0; if still malformed, score = 0.0, `note = "scorer_error: malformed_response"` |
| LLM score out of range [0.0, 1.0] | Clamp to [0.0, 1.0]; log warning |
| Redis write fails | Raise `StreamWriteError` (retryable); Temporal activity retries |
| Anthropic API connection error | Raise retryable error; Temporal activity retries |

---

## Gherkin Coverage

Scenarios in `docs/features/claim-ingestion.feature`:

- **"Check-worthy claim proceeds to ANALYZING"** -- `CHECK_WORTHY_SCORE = 0.82` -> run continues, entity-extractor dispatched
- **"Below-threshold claim is cancelled"** -- `CHECK_WORTHY_SCORE = 0.31` -> run transitions to `cancelled`, no further dispatch, streams retained
- **"Claim detector publishes normalized claim text"** -- covers normalization before scoring

---

## Test Scenarios

### Unit tests (`tests/unit/agents/test_scorer.py`)

| Test | Input | Expected |
|---|---|---|
| Check-worthy factual claim | "Biden signed executive order 14042 on September 9 2021 mandating COVID vaccination for federal contractors." | score >= 0.7 |
| Pure opinion | "Politicians are all corrupt and only care about money." | score < 0.3 |
| Threshold boundary (proceed) | score = 0.40 | proceed = True |
| Threshold boundary (cancel) | score = 0.39 | proceed = False |
| Perfect score | score = 1.0 | proceed = True |
| Zero score | score = 0.0 | proceed = False |
| Malformed LLM response (after retries) | `{"score": "high"}` | score = 0.0, note contains "scorer_error" |
| Score out of range | `{"score": 1.5}` | score clamped to 1.0 |

### Integration tests (`tests/integration/agents/test_claim_detector.py`)

| Test | Assertion |
|---|---|
| End-to-end check-worthy claim | Stream contains P then F observation for CHECK_WORTHY_SCORE; STOP finalStatus = "F" |
| End-to-end below-threshold claim | Stream contains P then F observation; STOP finalStatus = "X" |
| Stream message ordering | seq values are 1-based and monotonically increasing |
| Observation count in STOP | `observationCount` matches actual OBS messages published |
| Progress events published | `progress:{runId}` contains scoring and gate decision messages |
