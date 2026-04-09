---
id: NFR-021
title: "SYNTHESIS_SIGNAL_COUNT Accurately Reflects Evidence Breadth"
status: accepted
category: correctness
subcategory: functional-correctness
priority: must
components: [synthesizer]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-021: SYNTHESIS_SIGNAL_COUNT Accurately Reflects Evidence Breadth

## Context

The synthesizer's signal count drives confidence scoring. If it does not match the actual number of F/C status observations consumed, confidence scores will be miscalibrated and verdicts unreliable.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Discrepancy between reported SYNTHESIS_SIGNAL_COUNT and actual F/C observation count |
| **Meter**  | Comparison for all 50 corpus claims |
| **Must**   | Zero discrepancy across all 50 claims |
| **Plan**   | Zero discrepancy across all 50 claims |
| **Wish**   | Zero discrepancy across all 50 claims |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Orchestrator |
| **Stimulus**       | A claim is processed with all 10 agents active |
| **Environment**    | Normal operation, all external APIs returning data |
| **Artifact**       | Synthesizer |
| **Response**       | Synthesizer records the number of F/C status observations used as inputs |
| **Response Measure** | SYNTHESIS_SIGNAL_COUNT matches the actual count of F/C status observations included in the synthesizer's consolidated observation log, verified for all 50 corpus claims |

## Verification

- **Automated**: TBD
- **Manual**: For each corpus claim, compare SYNTHESIS_SIGNAL_COUNT to actual F/C observation count
