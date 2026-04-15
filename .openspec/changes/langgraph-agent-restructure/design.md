## Context

The agent-service completed a major architectural migration (tracked in `langgraph-pipeline-migration`): 11 class-based agent handlers orchestrated by a Temporal DAG were replaced with 5 pure-function pipeline nodes running inside a single LangGraph StateGraph. The old handler classes (`FanoutBase`, `LangGraphBase`, `ToolRuntime`), DAG infrastructure (`workflows/dag.py`, `activities/run_agent.py`), and per-agent handler directories have all been deleted (commits `f142e8a`, `7b75e2a`, `64838bf`, `8b50d46`, `f51f38c`, `61c0f7f`).

The pipeline nodes are implemented and unit-tested. However, the migration left gaps:

1. **No integration tests** — Nodes are tested with mocked Redis and Temporal. No tests verify observation publishing to real Redis, full-pipeline state flow, or Temporal heartbeat behavior.
2. **Incomplete Temporal workflow** — ADR-0023 specifies a 4-activity pattern (validate_input → run_pipeline → persist_verdict → notify_frontend) but the current workflow only calls `run_langgraph_pipeline`. The persist and notify activities don't exist yet.
3. **Observation coverage unverified** — 36 OBX codes are defined in `models/observation.py`. No test verifies that the pipeline emits all codes for a check-worthy claim.
4. **Two stale openspec changes** — `simplify-langgraph-temporal-layering` (42 tasks, all unchecked, code deleted) and `refactor-entity-extractor-langgraph` (tasks obsolete, entity extraction now in intake node).

Constraints: The agent-service runs in Docker Compose with Redis on port 6379. Integration tests must work with `docker compose up` and with pytest's async fixtures. The NestJS backend starts Temporal workflows via `@temporalio/client`.

## Goals / Non-Goals

**Goals:**
- Verify end-to-end pipeline correctness with integration tests against real Redis
- Complete the Temporal workflow to the 4-activity pattern from ADR-0023
- Confirm all 36 OBX codes are emitted in correct node order
- Clean up stale openspec changes that no longer reflect reality
- Promote ADR-0023 from `proposed` to `accepted`

**Non-Goals:**
- Rewriting the existing pipeline nodes (they work; this is about testing and completion)
- Adding new observation codes or changing the OBX registry
- Modifying the NestJS backend beyond what's needed for PipelineResult consumption
- Migrating from Redis Streams to Kafka (that's a separate ADR-012 concern)
- Adding LangGraph checkpointing (future capability, not needed for current flow)

## Decisions

### D1: Integration test infrastructure uses pytest-docker fixtures

Integration tests will use a `conftest.py` that connects to the Docker Compose Redis instance. Tests create isolated stream keys per test using unique run_ids to avoid cross-test contamination. No embedded Redis — the Docker Compose stack is the test environment.

**Alternative considered**: testcontainers-python for ephemeral Redis. Rejected because Docker Compose is already the standard dev environment, and testcontainers adds a dependency that duplicates existing infrastructure.

### D2: Per-node integration tests verify observation publishing

Each pipeline node gets an integration test that:
1. Creates a real `RedisReasoningStream` and `PipelineContext`
2. Runs the node with realistic input state
3. Reads observations back from Redis and asserts on codes, sequence, agent identity, and epistemic status
4. Verifies the node's state output matches expected keys

This is the layer between unit tests (mocked everything) and E2E tests (full pipeline).

### D3: Full-pipeline integration test runs complete graph

One integration test invokes `pipeline_graph.ainvoke()` with a real PipelineContext and a check-worthy claim. It verifies:
- All 5 nodes execute in correct order (intake → [evidence, coverage] → validation → synthesizer)
- Final state contains verdict, confidence, narrative
- Redis streams contain observations from all agents
- Observation count matches expected minimum

### D4: Temporal workflow adds persist_verdict and notify_frontend activities

The current workflow calls only `run_langgraph_pipeline`. ADR-0023 specifies two additional activities:
- `persist_verdict`: Takes PipelineResult + session_id, persists verdict/confidence/narrative to the run status store
- `notify_frontend`: Publishes a `VERDICT_READY` event to the progress stream for SSE relay

These are thin activities — the persist logic reuses `run_status.update_run_status` and the notify logic reuses `PipelineContext.publish_progress`. The workflow becomes:
```
validate_input → run_pipeline → persist_verdict → notify_frontend
```

`validate_input` is already implicit in the workflow's pre-checks. We'll extract it as an explicit activity for symmetry and testability.

### D5: Observation completeness is tested via a manifest

Rather than hardcoding expected codes in tests, create a `tests/fixtures/observation_manifest.json` that maps each pipeline node to its expected OBX codes. The full-pipeline integration test loads this manifest and asserts coverage. The manifest is derived from `models/observation.py`'s `_CODE_METADATA` registry.

This makes the test self-updating when new codes are added — update the manifest, not the test logic.

### D6: Stale changes are archived, not deleted

`simplify-langgraph-temporal-layering` and `refactor-entity-extractor-langgraph` will be archived using `openspec archive`. Their tasks are obsolete but their design documents contain useful decision rationale. Archival preserves history while removing them from active status.

## Risks / Trade-offs

**[Integration tests depend on Docker Compose running]** → Tests are marked with `@pytest.mark.integration` and skipped when Redis is unavailable. CI runs Docker Compose before the integration test stage. Dev workflow: `docker compose up -d redis && pytest -m integration`.

**[4-activity pattern adds latency vs single activity]** → Minimal: persist_verdict and notify_frontend are sub-second operations (one DB write, one Redis XADD). The pipeline activity (run_langgraph_pipeline) dominates at 10-60s. The 4-activity pattern improves observability and retry granularity.

**[Observation manifest drift]** → The manifest is checked against `_CODE_METADATA` in a unit test. If a code is added to the registry but missing from the manifest, the test fails. This is intentional — new codes require explicit test coverage decisions.

**[Backend PipelineResult format change]** → The NestJS backend currently parses workflow results. If PipelineResult fields change, the backend's Temporal client adapter needs updating. Risk is low — PipelineResult is already defined and stable.
