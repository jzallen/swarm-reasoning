## Context

The ingestion agent is Phase 1 of every fact-checking run. The `ClaimVerificationWorkflow` dispatches it first as a Temporal activity, before any other agents. It must:

1. Receive a raw claim submission (text, optional source URL, optional source date)
2. Validate the submission structurally and reject non-check-worthy inputs early
3. Publish three factual `CLAIM_*` observations (`CLAIM_TEXT`, `CLAIM_SOURCE_URL`, `CLAIM_SOURCE_DATE`) with status `F`
4. Classify the claim's domain using Claude and publish `CLAIM_DOMAIN` with status `F`
5. Close the stream with `finalStatus=F` on success or `finalStatus=X` if the claim fails validation
6. Publish progress events to `progress:{runId}` for SSE relay to the frontend

The agent runs as a Temporal activity worker within the shared Python agent-service container (ADR-0016). The orchestrator is a Temporal workflow that dispatches this agent via `workflow.execute_activity()`. The agent never calls other agents directly.

Key constraints from ADRs:
- ADR-004: Tool layer constructs and publishes all observations -- the LLM never generates raw observation JSON
- ADR-016: Agent is a Temporal activity worker, not an MCP server; no per-agent container
- ADR-003: Observations are append-only -- once published, never modified; corrections use status `C`
- ADR-011: JSON observation schema over Redis Streams
- ADR-013: Temporal (control) and Redis Streams (data) fail independently

## Goals / Non-Goals

**Goals:**
- Validate claim submissions against structural rules before publishing to the stream
- Publish all four `CLAIM_*` observations with correct epistemic status
- Classify domain using Claude with retry on ambiguous output
- Implement duplicate detection scoped to the run (same claim text, same `runId`)
- Run as a Temporal activity within the shared agent-service container
- Publish progress events for frontend visibility
- Fail fast with `finalStatus=X` and emit a single `CLAIM_TEXT` observation with status `X` when the gate rejects the claim

**Non-Goals:**
- Check-worthiness scoring (owned by `claim-detector`)
- Named entity extraction (owned by `entity-extractor`)
- Normalization of claim text (owned by `claim-detector`)
- Source credibility assessment
- Any UI or REST API surface (owned by NestJS backend)
- Per-agent Dockerfile or docker-compose entry (runs in shared container per ADR-0016)

## Decisions

### 1. Two LangChain tools invoked within a single Temporal activity

`ingest_claim` and `classify_domain` are separate LangChain tools called sequentially within the `run_agent_activity` Temporal activity. This allows the orchestrator to potentially retry the expensive LLM classification step independently from the cheap validation step (via activity retry on the classify step specifically, if split into sub-activities in future).

The Temporal activity function calls:
1. `ingest_claim(run_id, claim_text, source_url, source_date)` -- validation + CLAIM_TEXT/URL/DATE observations
2. `classify_domain(run_id, claim_text)` -- LLM classification + CLAIM_DOMAIN observation + STOP

**Alternative considered:** Single monolithic function. Rejected -- coupling prevents independent retry of the expensive LLM step.

### 2. Status promotion pattern for CLAIM_DOMAIN

`CLAIM_DOMAIN` starts as `P` (preliminary) when the LLM returns a result on the first attempt and is promoted to `F` (final) once the tool confirms the value is in the controlled vocabulary. If the first attempt returns an unrecognized value, the tool retries once before falling back. The `P` -> `F` promotion is implemented by publishing a second observation with status `F` and the same code -- the synthesizer selects the most recent `F` per ADR-003.

**Alternative considered:** Publish `F` directly without `P`. Rejected -- the preliminary/final distinction lets downstream consumers distinguish "classification in progress" from "classification settled."

### 3. Validation order: structural first, semantic second

Structural validation (text length, URL format, date format) happens before the LLM call. If structural validation fails, no LLM call is made. This minimizes API cost on malformed inputs.

Checks in order:
1. Text length: 5-2000 characters (too short = not a claim, too long = submit excerpt)
2. URL format: if present, must match `https?://` with TLD; URL reachability is NOT checked
3. Date format: if present, normalize to YYYYMMDD; reject if non-parseable
4. Duplicate detection: Redis `GET reasoning:dedup:{runId}:{claim_hash}` -- reject if key exists, set with TTL=24h on success

### 4. Domain classification via Claude claude-sonnet-4-6 with structured output

The classification tool calls the Anthropic API with a system prompt that constrains the response to exactly one token from the controlled vocabulary. The prompt instructs Claude to respond with only one of: `HEALTHCARE`, `ECONOMICS`, `POLICY`, `SCIENCE`, `ELECTION`, `CRIME`, `OTHER`. If the response contains anything not in this list, retry once. If the retry also fails, publish `CLAIM_DOMAIN` with value `OTHER` and status `F`, and include a note explaining the fallback.

### 5. Package structure (within shared agent-service)

```
services/
  agent-service/
    src/
      agents/
        ingestion_agent/
          __init__.py
          handler.py       -- IngestionAgentHandler: run() entry point called by Temporal activity
          tools/
            __init__.py
            claim_intake.py  -- ingest_claim tool implementation
            domain_cls.py    -- classify_domain tool implementation
          validation.py    -- structural validators (text, URL, date, dedup)
    tests/
      unit/
        agents/
          test_validation.py
          test_domain_cls.py
      integration/
        agents/
          test_ingestion_flow.py   -- full START->OBS->STOP round-trip against live Redis
```

No per-agent Dockerfile. No per-agent docker-compose entry. The agent runs within the shared `agent-service` container that hosts all Temporal activity workers.

### 6. Stream lifecycle responsibility

The `ingest_claim` tool publishes `START` before the first observation. `classify_domain` publishes `STOP` after the last observation. If validation fails in `ingest_claim`, that tool publishes both `START` and `STOP` (with `finalStatus=X`). The Temporal activity orchestrates the calling order.

### 7. Progress events

The agent publishes progress events to `progress:{runId}` at key milestones:
- `"Validating claim submission..."` -- after activity starts
- `"Claim accepted, classifying domain..."` -- after validation passes
- `"Domain classified: {domain}"` -- after classification completes
- `"Claim rejected: {reason}"` -- on validation failure

These events are relayed by the NestJS backend to the frontend via SSE (ADR-018).

## Risks / Trade-offs

- **[LLM classification latency]** -- Claude call adds ~1-2s to Phase 1. Acceptable -- ingestion is sequential; fanout does not start until ingestion STOP is observed.
- **[Anthropic API unavailability]** -- Classification fails; the Temporal activity raises a retryable error. Temporal retries up to 3 times. If all retries fail, fallback to `OTHER` is published and the run proceeds with reduced domain specificity.
- **[Duplicate detection TTL]** -- 24h TTL means the same claim can be re-submitted after 24h. Intentional -- allows re-investigation of evolving stories.
- **[URL reachability not checked]** -- An unreachable URL passes validation. The source URL is metadata only; agents retrieve the content separately.
