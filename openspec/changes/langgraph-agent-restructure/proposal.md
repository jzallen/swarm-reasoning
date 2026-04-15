## Why

The LangGraph pipeline migration (openspec change `langgraph-pipeline-migration`) is 76% complete: all 5 pipeline nodes are implemented and unit-tested, old handler/DAG/base-class code is deleted, and ADR-0023 documents the decision. However, 8 tasks remain unchecked — primarily integration tests, Temporal workflow completion (the 4-activity pattern from M8), NestJS backend verification, and final orphan-check verification. Additionally, the prior change `simplify-langgraph-temporal-layering` defined 42 tasks that are now obsolete because the code they targeted was deleted wholesale rather than refactored. The old `.openspec/changes/` specs (16 change sets) still describe the pre-migration 11-agent architecture. Without completing the integration layer and aligning specs to reality, the system has working nodes but unverified end-to-end behavior.

## What Changes

- **Pipeline integration tests**: End-to-end tests for each pipeline node against real Redis, plus a full-pipeline integration test verifying observation publishing and state flow
- **Temporal workflow completion**: Wire the simplified 4-activity pattern (validate_input → run_pipeline → persist_verdict → notify_frontend) per ADR-0023 section on workflow simplification
- **Backend compatibility verification**: Ensure NestJS backend starts the new workflow correctly and consumes PipelineResult for session/verdict persistence
- **ADR-0023 finalization**: Promote status from `proposed` to `accepted`, add measured outcomes from the migration
- **Observation completeness audit**: Verify all 36 observation codes from the OBX registry are properly emitted by the pipeline nodes in correct sequence
- **Stale spec retirement**: Archive the 2 superseded openspec changes (`simplify-langgraph-temporal-layering`, `refactor-entity-extractor-langgraph`) whose tasks are obsolete
- **Final cleanup verification**: Grep-based audit for orphaned imports, unused test fixtures, and stale references to deleted modules

## Capabilities

### New Capabilities
- `pipeline-integration-tests`: Integration test suite for the LangGraph pipeline — per-node tests against real Redis, full-pipeline E2E test, observation sequence verification, error path validation
- `temporal-workflow-completion`: Finalized 4-activity Temporal workflow (validate_input → run_pipeline → persist_verdict → notify_frontend) with retry policies, timeout configuration, and cancellation propagation
- `observation-completeness-audit`: Verification that all 36 OBX codes are emitted by the correct pipeline node in the correct sequence with correct epistemic status transitions

### Modified Capabilities

## Impact

- **Agent service (Python)**: New `tests/integration/pipeline/` directory with per-node and full-pipeline integration tests. Updates to `workflows/claim_verification.py` for 4-activity pattern. Updates to `activities/` for persist_verdict and notify_frontend activities.
- **NestJS backend**: Verification of Temporal client workflow start and PipelineResult consumption. May need minor updates to result parsing.
- **ADR-0023**: Status change from `proposed` to `accepted`.
- **OpenSpec**: Two stale changes archived. Remaining pipeline-migration tasks checked off as work is verified complete.
- **Tests**: ~15-20 new integration test cases across pipeline nodes and Temporal workflow.
