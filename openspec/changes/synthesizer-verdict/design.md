# Design -- synthesizer-verdict

## Context

The synthesizer operates as the final agent in Phase 3 of the execution DAG. The orchestrator Temporal workflow invokes it after receiving completion results from all ten upstream agents (including the blindspot-detector which runs earlier in Phase 3). By the time the synthesizer runs, the Redis Streams for a given `runId` contain 60-80 immutable OBX observations from agents: ingestion-agent, claim-detector, entity-extractor, claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence, source-validator, and blindspot-detector.

The synthesizer is stateless with respect to the observations themselves: it reads the append-only streams (ADR-003) via the ReasoningStream interface, applies resolution rules, computes scores, maps to a verdict, generates a narrative, and publishes five OBX rows plus a STOP message. It never modifies upstream observations. It runs as a Temporal activity worker in the shared agent-service container (ADR-0016).

The system must produce a confidence-scored verdict using PolitiFact's six-tier rating scale (per docs/domain/entities/verdict.md). An additional UNVERIFIABLE verdict is used when evidence is insufficient (SYNTHESIS_SIGNAL_COUNT < 5). A ClaimReview override path allows a high-confidence external fact-check to supersede the swarm's computed score. SOURCE_CONVERGENCE_SCORE from the source-validator strengthens confidence scoring, and CITATION_LIST feeds directly into the verdict annotation.

## Goals

1. Resolve conflicting upstream observations deterministically using epistemic status precedence (ADR-003, ADR-005).
2. Produce a calibrated CONFIDENCE_SCORE from a weighted signal model across all upstream agent findings, incorporating SOURCE_CONVERGENCE_SCORE as a confidence amplifier.
3. Map CONFIDENCE_SCORE to one of seven verdict codes using the fixed threshold ranges from docs/domain/entities/verdict.md (True=0.90-1.00, Mostly True=0.70-0.89, Half True=0.45-0.69, Mostly False=0.25-0.44, False=0.10-0.24, Pants on Fire=0.00-0.09).
4. Override the swarm verdict with the ClaimReview verdict when external fact-check confidence is high, and record the reason.
5. Generate a human-readable narrative that explains the verdict with traceable citations to upstream OBX sequence numbers and annotated source URLs from CITATION_LIST.
6. Achieve >= 70% correct verdict alignment on the 50-claim PolitiFact corpus (NFR-019).
7. Emit SYNTHESIS_SIGNAL_COUNT that exactly matches the count of F/C observations consumed (NFR-021).

## Key Decisions

### Observation Resolution: C > F, X and P excluded (ADR-003, ADR-005)

For each unique (agent, code) pair, the canonical value is determined by:
1. If any C-status observation exists for this pair, use the one with the highest sequence number.
2. Otherwise, if any F-status observation exists, use the one with the highest sequence number.
3. X-status and P-status observations are excluded from the synthesis input set.

Rationale: Corrections (C) represent acknowledged errors. X-status represents cancelled/superseded findings. P-status is preliminary and not yet finalized. The append-only log is authoritative; the resolution algorithm is a read-time view, never a write.

SYNTHESIS_SIGNAL_COUNT is the count of (agent, code) pairs that contribute at least one F or C observation after this resolution step.

The synthesizer now reads from 10 upstream agent streams (not 9), including source-validator's stream which contains SOURCE_EXTRACTED_URL, SOURCE_VALIDATION_STATUS, SOURCE_CONVERGENCE_SCORE, and CITATION_LIST observations.

### Confidence Score: Weighted Signal Model with Convergence

The confidence score is not an LLM output. It is a deterministic weighted combination of resolved upstream signals. This keeps the scoring auditable and reproducible. LLM involvement is limited to the narrative generation step.

Signal weights (normalized):
- `DOMAIN_EVIDENCE_ALIGNMENT`: 0.30 (primary source evidence)
- `CLAIMREVIEW_MATCH` + `CLAIMREVIEW_VERDICT`: 0.25 (external fact-check, trust-adjusted by `CLAIMREVIEW_MATCH_SCORE`)
- `CROSS_SPECTRUM_CORROBORATION`: 0.15 (corroboration across political spectrum)
- `COVERAGE_FRAMING` (left + center + right): 0.15 (framing consensus)
- `SOURCE_CONVERGENCE_SCORE`: 0.10 (source convergence across agents -- per ADR-0021)
- `DOMAIN_CONFIDENCE`: 0.05 (domain evidence confidence penalty)

Blindspot penalty: CONFIDENCE_SCORE is reduced by `BLINDSPOT_SCORE * 0.10` after weighted summation. This caps the penalty at 0.10 for a complete blindspot.

When SYNTHESIS_SIGNAL_COUNT < 5, CONFIDENCE_SCORE is not computed and VERDICT is forced to UNVERIFIABLE.

### Verdict Mapping: Fixed Thresholds from verdict.md

CONFIDENCE_SCORE maps to verdict via the threshold ranges defined in docs/domain/entities/verdict.md:

| Range        | Verdict       | CWE Code                              |
|--------------|---------------|---------------------------------------|
| 0.90-1.00    | TRUE          | `TRUE^True^POLITIFACT`                       |
| 0.70-0.89    | MOSTLY_TRUE   | `MOSTLY_TRUE^Mostly True^POLITIFACT`         |
| 0.45-0.69    | HALF_TRUE     | `HALF_TRUE^Half True^POLITIFACT`             |
| 0.25-0.44    | MOSTLY_FALSE  | `MOSTLY_FALSE^Mostly False^POLITIFACT`       |
| 0.10-0.24    | FALSE         | `FALSE^False^POLITIFACT`                     |
| 0.00-0.09    | PANTS_FIRE    | `PANTS_FIRE^Pants on Fire^POLITIFACT`        |
| N/A          | UNVERIFIABLE  | `UNVERIFIABLE^Unverifiable^FCK`       |

Boundaries are inclusive on the lower bound and exclusive on the upper bound, except TRUE which is inclusive on both.

### ClaimReview Override

When CLAIMREVIEW_MATCH is TRUE and CLAIMREVIEW_MATCH_SCORE >= 0.90, the synthesizer may override the swarm verdict with the ClaimReview verdict. The override fires when:
- The ClaimReview verdict differs from the swarm-computed verdict, AND
- CLAIMREVIEW_MATCH_SCORE >= 0.90

When the override fires, SYNTHESIS_OVERRIDE_REASON is populated with a structured string referencing the ClaimReview source, match score, and the swarm's computed confidence. When verdicts agree, SYNTHESIS_OVERRIDE_REASON is an empty string.

Rationale: ClaimReview entries are produced by professional fact-checkers. A very high semantic match (>= 0.90) means the same claim was evaluated. This threshold prevents false overrides from loose matches.

### Narrative Generation with Source Citations

VERDICT_NARRATIVE is the only synthesizer output generated by an LLM call. The prompt includes:
- Input: resolved observation set with (code, value, seq, agent) tuples
- Input: CITATION_LIST from source-validator (annotated source URLs with validation status)
- Constraint: cite at least three upstream OBX observations by sequence number
- Constraint: include source citations with validation status from CITATION_LIST
- Constraint: 200-1000 characters
- Constraint: use plain language; no hedging if verdict is UNVERIFIABLE (explain missing evidence instead)

The narrative cites observations as `[OBX-{seq}]` inline and includes source URLs with validation notes (e.g., "[source: CDC (live)]", "[source: Reuters (dead link)]"). The synthesizer tool layer validates length before publishing.

### All Synthesizer Observations at F Status

The synthesizer never emits P or C observations. Every OBX it publishes is F-status. The rationale: synthesis is a terminal, non-preliminary operation. There is no agent that corrects synthesizer output; corrections flow to the consumer API as new runs.

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Upstream P-status observations not yet finalized at synthesis time | Low (orchestrator gates on all STOP messages) | Resolution algorithm excludes P; VERDICT_NARRATIVE notes incomplete signals when any P is encountered |
| LLM narrative generation exceeds token budget or latency SLA | Medium | Hard timeout on narrative call (5 s); fallback to template-generated narrative if LLM fails |
| ClaimReview override fires on loose match (score 0.75-0.89) | Low (threshold is 0.90) | Threshold chosen conservatively; SYNTHESIS_OVERRIDE_REASON always records the match score for auditability |
| SYNTHESIS_SIGNAL_COUNT drift from actual count | Low (deterministic algorithm) | Unit-tested with exact count assertions; NFR-021 verified by validation harness |
| Confidence score miscalibration on sparse evidence sets | Medium | UNVERIFIABLE verdict at < 5 signals prevents false precision; NFR-019 monitored against corpus |
| SOURCE_CONVERGENCE_SCORE absent when source-validator failed | Low | Treated as 0.0 contribution; weight redistributed to other present signals via effective weight normalization |
