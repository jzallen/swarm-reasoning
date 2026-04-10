## Why

Nine slices have delivered the full swarm: observation schema, orchestrator, ingestion, claim detection, entity extraction, parallel fan-out agents (coverage left/center/right, ClaimReview matcher), domain evidence, blindspot detection, synthesizer, and the NestJS backend. The system can process claims end-to-end. But "it runs" is not the same as "it works." Without a validation harness, there is no reproducible way to determine whether the swarm produces accurate verdicts, whether it outperforms a single-agent baseline, or whether it satisfies NFR-019 (≥ 70% corpus accuracy) and NFR-020 (≥ 20 pp advantage over single-agent on non-indexed claims). This slice closes the loop: it delivers the fixture corpus, the scoring engine, and the comparative baseline runner that together make the system measurably correct.

## What Changes

- Assemble and commit the 50-claim PolitiFact validation corpus as a structured JSON fixture (`docs/validation/corpus.json`), stratified across five categories per ADR-0008
- Implement an automated accuracy scorer that processes corpus runs and produces per-category alignment rates using the within-one-tier rule
- Implement a single-agent baseline runner (ClaimReview-only, no swarm) to establish the counterfactual for NFR-020 comparison
- Wire all nine Gherkin scenarios from `validation-baseline.feature` to runnable step implementations
- Add a Makefile / CI target `make validate` that runs the full 50-claim corpus and emits a structured accuracy report

## Capabilities

### New Capabilities

- `politifact-corpus`: 50-claim JSON fixture with ground truth PolitiFact verdicts, claim text, URLs, and category labels. Stratified into five category sets as specified by ADR-0008. Not generated — curated and committed as a deterministic test fixture.
- `accuracy-measurement`: Automated scoring engine that submits corpus claims to the running swarm, collects published verdicts, and computes per-category alignment rates using within-one-tier scoring. Emits a structured JSON report and a human-readable summary table.
- `baseline-comparison`: Single-agent baseline runner that calls only the ClaimReview lookup path (no parallel agents) on the 10 non-indexed claims, records the baseline alignment rate, and computes the swarm-vs-baseline gap for NFR-020 verification.

### Modified Capabilities

- `nestjs-backend` (slice 5): No structural changes. The harness consumes existing `/sessions/:id/verdict` and `/sessions/:id/observations` endpoints.

## Impact

- **New file**: `docs/validation/corpus.json` — 50-claim fixture, committed to the repository
- **New package**: `tests/validation/` (Python) — harness runner, scorer, baseline runner, Cucumber step bindings
- **CI integration**: `make validate` target runs against a live stack (`docker compose up`) and exits non-zero if NFR-019 or NFR-020 thresholds are breached
- **No new containers**: Harness runs as a Python process against the existing 8-service stack
- **Documentation**: Accuracy report template added to `docs/validation/`
