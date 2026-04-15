# Tasks -- synthesizer-verdict

## 1. Package Setup

- [x] 1.1 Create `src/swarm_reasoning/agents/synthesizer/` package directory with `__init__.py`
- [x] 1.2 Create module files: `resolver.py`, `scorer.py`, `mapper.py`, `narrator.py`, `activity.py`, `models.py`
- [x] 1.3 Add dependencies to agent-service requirements: `anthropic` Python SDK, `pydantic>=2.0`

## 2. Capability: observation-resolution

- [x] 2.1 Implement `ResolvedObservation` and `ResolvedObservationSet` dataclasses in `models.py`
- [x] 2.2 Implement `ObservationResolver` class in `resolver.py` with `resolve(run_id, stream) -> ResolvedObservationSet`
- [x] 2.3 Implement stream reading: reads all 10 upstream agent streams via `stream.xrange()`, including source-validator
- [x] 2.4 Implement C > F precedence per (agent, code) pair; exclude X and P status; record resolution_method
- [x] 2.5 Compute synthesis_signal_count as count of resolved (agent, code) pairs; populate excluded_observations and warnings
- [x] 2.6 Write unit tests for resolution: C wins over F, latest-by-seq among multiple C/F, X excluded, P excluded with warning, mixed statuses, NFR-021 count accuracy, source-validator observations included

## 3. Capability: confidence-scoring

- [x] 3.1 Implement `ConfidenceScorer` class in `scorer.py` with `compute(resolved) -> float | None`
- [x] 3.2 Return None when synthesis_signal_count < 5
- [x] 3.3 Implement Component A -- Domain Evidence (weight 0.30): map alignment to score, multiply by DOMAIN_CONFIDENCE
- [x] 3.4 Implement Component B -- ClaimReview (weight 0.25): map verdict to truthfulness score when match is TRUE, weight by match score
- [x] 3.5 Implement Component C -- Cross-Spectrum Corroboration (weight 0.15): TRUE=1.0, FALSE=0.0
- [x] 3.6 Implement Component D -- Coverage Framing Consensus (weight 0.15): average framing scores across 3 agents
- [x] 3.7 Implement Component E -- Source Convergence (weight 0.10): use SOURCE_CONVERGENCE_SCORE directly per ADR-0021
- [x] 3.8 Implement normalization by effective weight total and blindspot penalty (BLINDSPOT_SCORE * 0.10)
- [x] 3.9 Write unit tests for scoring: full evidence set, missing ClaimReview, blindspot penalty, insufficient signals, effective weight normalization, convergence score impact

## 4. Capability: verdict-mapping

- [x] 4.1 Implement `VerdictMapper` class in `mapper.py` with `map_verdict(confidence_score, resolved) -> (verdict, override_reason)`
- [x] 4.2 Implement threshold table per docs/domain/entities/verdict.md: True=0.90-1.00, Mostly True=0.70-0.89, Half True=0.45-0.69, Mostly False=0.25-0.44, False=0.10-0.24, Pants on Fire=0.00-0.09
- [x] 4.3 Implement ClaimReview override logic: fires when match score >= 0.90, verdicts differ, score is not None
- [x] 4.4 Override reason string includes source, match score, swarm verdict, confidence score; empty string when no override
- [x] 4.5 Write unit tests for all six verdict thresholds (0.95, 0.75, 0.55, 0.35, 0.18, 0.04)
- [x] 4.6 Write unit tests for boundary values: 0.90->TRUE, 0.8999->MOSTLY_TRUE, 0.70->MOSTLY_TRUE, 0.6999->HALF_TRUE, 0.45->HALF_TRUE, 0.4499->MOSTLY_FALSE, 0.25->MOSTLY_FALSE, 0.2499->FALSE, 0.10->FALSE, 0.0999->PANTS_FIRE
- [x] 4.7 Write unit tests for None->UNVERIFIABLE, override fires/does not fire, override reason empty vs non-empty

## 5. Capability: verdict-narrative

- [x] 5.1 Implement `NarrativeGenerator` class in `narrator.py` with `generate(resolved, verdict, confidence_score, override_reason, warnings, signal_count, citation_list) -> str`
- [x] 5.2 Build structured LLM prompt with observation list, verdict, CITATION_LIST source annotations, override, warnings
- [x] 5.3 Implement 5s hard timeout on Anthropic API call
- [x] 5.4 Implement length validation: [200, 1000]; retry once if too short; truncate at last sentence if too long
- [x] 5.5 Implement fallback template when LLM fails, producing >= 200 characters with source citation summary
- [x] 5.6 Write unit tests: length bounds, OBX citation, CITATION_LIST source references, fallback triggers, truncation, UNVERIFIABLE explanation, P-status warnings, dead link annotation

## 6. Synthesizer Activity

- [x] 6.1 Implement `SynthesizerActivity(FanoutActivity)` in `activity.py`
- [x] 6.2 Implement `_execute()`: resolve -> score -> map -> narrate in sequence
- [x] 6.3 Publish START, then SYNTHESIS_SIGNAL_COUNT (seq 1), CONFIDENCE_SCORE (seq 2, skip if None), VERDICT (seq 3), VERDICT_NARRATIVE (seq 4), SYNTHESIS_OVERRIDE_REASON (seq 5)
- [x] 6.4 Publish STOP with finalStatus="F" and correct observationCount (4 or 5)
- [x] 6.5 Publish progress events: "Resolving observations...", "Computing confidence...", "Mapping verdict...", "Generating narrative...", "Verdict: {verdict}"
- [x] 6.6 Handle errors: publish STOP finalStatus=X, return FanoutActivityResult with status="CANCELLED"

## 7. Temporal Activity Registration

- [x] 7.1 Register `run_synthesizer` activity with @activity.defn, start_to_close_timeout=60s, max_attempts=2
- [x] 7.2 Write unit test: activity is importable with correct decorator

## 8. Integration Tests

- [x] 8.1 Write full integration test: synthetic observations from 10 agents -> all 5 OBX published with F-status
- [x] 8.2 Assert STOP finalStatus="F", SYNTHESIS_SIGNAL_COUNT matches input
- [x] 8.3 Assert CITATION_LIST reflected in VERDICT_NARRATIVE and SOURCE_CONVERGENCE_SCORE influences CONFIDENCE_SCORE
- [x] 8.4 Integration test: UNVERIFIABLE path (< 5 signals)
- [x] 8.5 Integration test: ClaimReview override path
- [x] 8.6 Integration test: progress events published to progress:{runId}

## 9. Run Lifecycle Integration

- [x] 9.1 Verify orchestrator transitions run to completed on successful synthesizer completion
- [x] 9.2 Verify orchestrator transitions run to FAILED on synthesizer failure
- [x] 9.3 Integration test: completed transition (verdict-synthesis.feature scenario)

## 10. Gherkin Step Definitions

- [ ] 10.1 Implement step definitions for verdict-synthesis.feature (13 scenarios)
- [ ] 10.2 Implement step definitions for verdict-publication.feature trigger/resolution scenarios
- [ ] 10.3 Remaining delivery/schema scenarios deferred to separate slice

## 11. Validation

- [ ] 11.1 Run verdict-synthesis.feature -- all 13 scenarios pass
- [x] 11.2 Run all unit tests (resolver, scorer, mapper, narrator) -- all pass
- [x] 11.3 Verify SYNTHESIS_SIGNAL_COUNT accuracy for 3 test runs (NFR-021)
- [x] 11.4 Verify threshold mapping matches docs/domain/entities/verdict.md exactly
- [x] 11.5 Verify CITATION_LIST sources appear in VERDICT_NARRATIVE for test runs
