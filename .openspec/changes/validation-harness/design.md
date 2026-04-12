## Context

All 11 agents (including the synthesizer) are implemented. The NestJS backend exposes verdicts. The system can process claims end-to-end. This slice adds the measurement layer: a deterministic fixture corpus, an automated scoring engine, and a single-agent baseline for comparative evaluation.

Key constraints from architecture docs:
- ADR-0008: PolitiFact corpus — 50 curated claims across five stratified categories; corpus is committed, not generated at runtime
- NFR-019: Correct alignment rate ≥ 70% (plan ≥ 80%, wish ≥ 90%) across all 50 claims
- NFR-020: Swarm must exceed single-agent baseline by ≥ 20 percentage points on non-indexed claims
- NFR-001: End-to-end run ≤ 120s; fan-out phase ≤ 45s
- NFR-022: Published verdicts must have ≥ 8 distinct agent streams in Redis (out of 11 agents total)
- `validation-baseline.feature`: 9 Gherkin scenarios that the harness must satisfy as executable acceptance tests

The "within-one-tier" rule: PolitiFact uses a six-tier scale (TRUE > MOSTLY_TRUE > HALF_TRUE > MOSTLY_FALSE > FALSE > PANTS_FIRE). A system verdict is "correct" if it falls within one tier of the ground truth in either direction. This rule is documented in `docs/domain/observation-schema-spec.md` Section 9 and governs both NFR-019 scoring and per-category Gherkin assertions.

## Goals / Non-Goals

**Goals:**
- Commit a curated, stable 50-claim corpus covering all five ADR-0008 categories
- Implement automated scoring that produces an authoritative accuracy report reproducible in CI
- Implement a minimal single-agent baseline for NFR-020 gap measurement
- Wire all 9 `validation-baseline.feature` scenarios to runnable step implementations
- Provide a `make validate` target that gates on NFR-019 and NFR-020 thresholds

**Non-Goals:**
- Expanding the corpus beyond 50 claims (ADR-0008 scope)
- Training or fine-tuning any model
- Building a UI for the accuracy report
- Evaluating the system on claim types outside the PolitiFact taxonomy
- Performance benchmarking beyond what NFR-001 requires

## Decisions

### 1. Corpus stored as committed JSON fixture, not generated at runtime

The corpus is curated, versioned, and committed to `docs/validation/corpus.json`. At runtime the harness reads this file — it does not scrape PolitiFact or call any external API to assemble the fixture. This ensures reproducibility: the same corpus is used in every CI run, across every branch.

**Alternative considered:** Scrape PolitiFact at test time. Rejected — corpus would drift as PolitiFact updates its archive, making test results non-reproducible.

### 2. Within-one-tier alignment as the correctness metric

The six-tier ordering (TRUE=5, MOSTLY_TRUE=4, HALF_TRUE=3, MOSTLY_FALSE=2, FALSE=1, PANTS_FIRE=0) is encoded in the scorer. A verdict is correct if `abs(system_tier - ground_truth_tier) <= 1`. This is the interpretation specified by NFR-019 and consistent with the Gherkin scenarios in `validation-baseline.feature`.

**Alternative considered:** Exact match scoring. Rejected — overcounts misses on ambiguous boundary claims; the system may legitimately score MOSTLY_TRUE for a TRUE claim.

### 3. Single-agent baseline uses ClaimReview-only path

The baseline runner submits the 10 non-indexed claims to a stripped Temporal workflow that activates only the `claimreview-matcher` activity and the `synthesizer` activity with only ClaimReview signal. Since these claims are not indexed, the baseline consistently receives no ClaimReview match, producing low-confidence or UNVERIFIABLE verdicts. This is the counterfactual that demonstrates swarm value.

**Alternative considered:** Use a single LLM call with no tools. Rejected — does not represent a realistic single-agent deployment; the ClaimReview-only path is the most defensible baseline because it is what a non-swarm fact-check system would do.

### 4. Corpus categories as first-class fixture fields

Each corpus entry carries a `category` field with one or more of the five labels:
- `TRUE_MOSTLY_TRUE`
- `FALSE_PANTS_FIRE`
- `HALF_TRUE`
- `CLAIMREVIEW_INDEXED`
- `NOT_CLAIMREVIEW_INDEXED`

The last two categories overlap the first three (a claim can be HALF_TRUE and CLAIMREVIEW_INDEXED). The 50-claim distribution satisfies: 10 per category, no claim appears in more than two categories. The `CLAIMREVIEW_INDEXED` and `NOT_CLAIMREVIEW_INDEXED` categories are mutually exclusive.

### 5. Harness parallelism: sequential submission with parallel polling

The harness submits claims sequentially (one POST per claim, no batching) but polls run status in parallel. This avoids exceeding the NestJS backend's concurrency limits while keeping total wall-clock time for the full corpus under 60 minutes.

**Alternative considered:** Batch all 50 claims simultaneously. Rejected — would require the orchestrator to handle 50 concurrent runs; not tested or validated in prior slices.

### 6. Accuracy report format

The harness writes `docs/validation/report-{timestamp}.json` after every corpus run. The JSON contains: per-claim results (claim ID, ground truth, system verdict, alignment score, run ID), per-category summary (alignment rate, mean confidence score, pass/fail against NFR threshold), and overall summary (total alignment rate, NFR-019 pass/fail, NFR-020 gap, NFR-020 pass/fail).

A human-readable table is printed to stdout and captured by CI.

## Risks / Trade-offs

- **[External API availability]** → The harness depends on Google Fact Check Tools API and NewsAPI being reachable. If either is down, corpus runs fail. Mitigation: harness retries with exponential backoff; CI marks the run as SKIPPED (not FAIL) on API unavailability.
- **[Corpus staleness]** → PolitiFact may revise verdicts after the corpus is committed. Mitigation: corpus entries include a `captured_date` field and `politifact_url` for manual re-verification; scheduled quarterly review.
- **[NFR-019 marginal threshold]** → At 70% must-threshold on 50 claims, a single outlier can tip pass/fail. Mitigation: report distinguishes must/plan/wish tiers; CI gates on must only.
- **[ClaimReview indexing drift]** → A "not indexed" claim may become indexed between corpus assembly and test execution. Mitigation: harness asserts `CLAIMREVIEW_MATCH == FALSE` for the 10 non-indexed entries; if the assertion fails, the run is flagged for corpus re-curation rather than failing NFR-020.
- **[Baseline runner complexity]** → The baseline requires a stripped Temporal workflow not used in production. Mitigation: baseline runner is test-only code in `tests/validation/baseline.py`; it calls the same NestJS backend API and does not bypass any production layer.
