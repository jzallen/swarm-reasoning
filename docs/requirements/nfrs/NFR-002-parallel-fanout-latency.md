---
id: NFR-002
title: "Parallel Fan-out Phase Latency"
status: accepted
category: performance
subcategory: time-behaviour
priority: must
components: [orchestrator, coverage-left, coverage-center, coverage-right, domain-evidence, blindspot-detector]
adrs: [ADR-009]
tests: []
date: 2026-04-09
---

# NFR-002: Parallel Fan-out Phase Latency

## Context

The parallel fan-out phase dispatches five agents simultaneously. If any agent stalls, it bottlenecks the entire run. Bounding this phase keeps end-to-end latency within acceptable limits.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Elapsed wall-clock time from fan-out dispatch to last agent STOP message |
| **Meter**  | Timer from orchestrator dispatch event to final STOP message receipt |
| **Must**   | <= 45 seconds |
| **Plan**   | <= 30 seconds |
| **Wish**   | <= 20 seconds |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Orchestrator |
| **Stimulus**       | Dispatches the five parallel agents simultaneously |
| **Environment**    | Normal operation |
| **Artifact**       | Parallel fan-out agents (coverage-left, coverage-center, coverage-right, domain-evidence, blindspot-detector) |
| **Response**       | All five agents publish STOP messages with terminal status |
| **Response Measure** | All five agents complete within 45 seconds of dispatch |

## Verification

- **Automated**: TBD
- **Manual**: Observe orchestrator logs for dispatch and STOP timestamps during a run
