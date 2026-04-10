---
id: NFR-019
title: "Swarm Verdict Accuracy on PolitiFact Corpus"
status: accepted
category: correctness
subcategory: functional-correctness
priority: must
components: [synthesizer, all-agents, backend-api]
adrs: []
tests: []
date: 2026-04-09
---

# NFR-019: Swarm Verdict Accuracy on PolitiFact Corpus

## Context

The system's core value proposition is accurate fact-checking. Verdict accuracy against a known corpus establishes a measurable baseline and validates that multi-agent reasoning produces reliable results.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Correct alignment rate (system verdict within one tier of PolitiFact verdict) |
| **Meter**  | Automated comparison across 50-claim PolitiFact validation corpus |
| **Must**   | >= 70% correct alignment |
| **Plan**   | >= 80% correct alignment |
| **Wish**   | >= 90% correct alignment |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Validation harness |
| **Stimulus**       | The 50-claim PolitiFact validation corpus is processed |
| **Environment**    | Normal operation, all external APIs reachable |
| **Artifact**       | Synthesizer, all agents |
| **Response**       | System produces verdicts for all 50 claims |
| **Response Measure** | Correct alignment rate (system verdict within one tier of PolitiFact verdict) is at least 70% across all 50 claims |

## Verification

- **Automated**: TBD
- **Manual**: Run full corpus through system and compare verdicts to PolitiFact ground truth
