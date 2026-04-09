---
id: NFR-020
title: "Swarm Outperforms Single-Agent on Non-Indexed Claims"
status: accepted
category: correctness
subcategory: functional-correctness
priority: must
components: [synthesizer, all-agents]
adrs: []
tests: []
date: 2026-04-09
---

# NFR-020: Swarm Outperforms Single-Agent on Non-Indexed Claims

## Context

The swarm architecture's complexity is justified only if it outperforms a single-agent baseline, especially on claims not already indexed by ClaimReview. This NFR validates the architectural bet.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Difference in correct alignment rate between swarm and single-agent baseline on non-indexed claims |
| **Meter**  | Comparative evaluation on 10 non-ClaimReview-indexed claims |
| **Must**   | Swarm exceeds single-agent by >= 20 percentage points |
| **Plan**   | Swarm exceeds single-agent by >= 30 percentage points |
| **Wish**   | Swarm exceeds single-agent by >= 40 percentage points |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Validation harness |
| **Stimulus**       | The 10 non-ClaimReview-indexed claims from the corpus are processed by both the swarm and a single-agent baseline |
| **Environment**    | Normal operation |
| **Artifact**       | Swarm system vs. single-agent baseline |
| **Response**       | Swarm correct alignment rate exceeds single-agent baseline |
| **Response Measure** | Swarm correct alignment rate on non-indexed claims exceeds single-agent baseline by at least 20 percentage points |

## Verification

- **Automated**: TBD
- **Manual**: Run non-indexed claims through both systems and compare alignment rates
