---
id: NFR-003
title: "Temporal Activity Dispatch Latency"
status: accepted
category: performance
subcategory: time-behaviour
priority: must
components: [orchestrator, temporal-server, agent-workers]
adrs: [ADR-016]
tests: []
date: 2026-04-09
---

# NFR-003: Temporal Activity Dispatch Latency

## Context

The orchestrator uses Temporal workflows to dispatch activities to agent workers. High dispatch latency (from workflow signal to worker pickup) compounds across multiple activities per run phase, directly inflating end-to-end latency.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | P99 latency for Temporal activity scheduling (from workflow signal to worker pickup) |
| **Meter**  | Instrumented timer on Temporal workflow measuring elapsed time from activity dispatch to worker task start |
| **Must**   | P99 < 2000 ms |
| **Plan**   | P99 < 1000 ms |
| **Wish**   | P99 < 500 ms |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Orchestrator workflow |
| **Stimulus**       | Dispatches an activity to an agent worker via Temporal |
| **Environment**    | Normal operation, agent workers healthy, Temporal server reachable |
| **Artifact**       | Temporal server, agent worker task queues |
| **Response**       | Agent worker picks up the activity and begins execution |
| **Response Measure** | P99 latency from workflow signal to worker pickup is under 2000 ms |

## Verification

- **Automated**: TBD
- **Manual**: Load-test Temporal activity dispatches and measure P99 scheduling latency
