---
status: accepted
date: 2026-04-08
deciders: []
---

# ADR-0008: PolitiFact Validation Corpus

## Context and Problem Statement

A multi-agent system producing fact-checking verdicts must be validated against known ground truth. Without a baseline, there is no way to distinguish a working system from a confidently wrong one. The validation strategy must use a corpus of claims with independently established verdicts, be reproducible, and cover a range of claim types and complexity levels.

PolitiFact publishes its full ruling history with claim text, verdict (True / Mostly True / Half True / Mostly False / False / Pants on Fire), source, and date. The corpus is publicly accessible, well-maintained, and covers thousands of claims across domains including healthcare, economics, and policy — all relevant to the system's intended use cases.

Google's Fact Check Tools API indexes ClaimReview markup from hundreds of fact-checking organizations including PolitiFact, Snopes, and FactCheck.org. This API is the system's primary fact-check retrieval mechanism and its output can be compared directly against PolitiFact's published verdicts.

## Decision Drivers

- Need for known ground truth to validate system verdicts
- Corpus must be publicly accessible and reproducible
- Must cover a range of claim types and complexity levels
- Must include claims both indexed and not indexed in ClaimReview to demonstrate swarm value

## Considered Options

1. **Synthetic claims** — Fabricated claims with predetermined verdicts. Controllable but not representative of real-world complexity.
2. **PolitiFact corpus** — Real claims with independently established verdicts, publicly accessible, well-maintained, covering diverse domains.
3. **Multi-source corpus** — Claims from multiple fact-checking organizations. Higher coverage but introduces cross-organization rating inconsistency.

## Decision Outcome

Chosen option: "PolitiFact corpus", because it provides independently established verdicts for real claims across diverse domains. The validation corpus is a curated set of 50 PolitiFact claims selected to cover:

- 10 claims with `True` or `Mostly True` verdicts
- 10 claims with `False` or `Pants on Fire` verdicts
- 10 claims with `Half True` verdicts (the hard middle)
- 10 claims indexed in Google Fact Check Tools API (ClaimReview present)
- 10 claims not yet indexed in ClaimReview (system must reason from coverage analysis and primary sources alone)

The last category is the most important for demonstrating swarm value: these are the claims a single agent calling ClaimReview would fail on, and where parallel coverage analysis and domain evidence agents provide signal unavailable to a monolithic approach.

### Consequences

- Good, because the system is validated against real-world claims with independently established ground truth
- Good, because the corpus includes claims that require swarm reasoning (not indexed in ClaimReview), demonstrating the value of the multi-agent approach
- Bad, because the validation corpus must be assembled and committed before any agent evaluation begins
- Bad, because verdict mapping from confidence scores to PolitiFact's six-tier scale requires a defined mapping convention (documented in the observation schema spec)
- Neutral, because the 50-claim corpus is intentionally small enough to inspect manually
