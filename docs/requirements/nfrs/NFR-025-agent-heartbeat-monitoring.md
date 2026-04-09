---
id: NFR-025
title: "Agent Heartbeat Is Monitored by Orchestrator"
status: accepted
category: observability
subcategory: fault-tolerance
priority: must
components: [orchestrator, all-agents]
adrs: [ADR-009, ADR-010]
tests: []
date: 2026-04-09
---

# NFR-025: Agent Heartbeat Is Monitored by Orchestrator

## Context

An unresponsive agent during fan-out could cause a run to hang indefinitely. Heartbeat monitoring enables the orchestrator to detect failures and transition the run to an error state promptly.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Time to detect agent heartbeat failure |
| **Meter**  | Timer from last heartbeat to orchestrator error detection |
| **Must**   | Detection within 30 seconds; run transitions to error state with agent identified |
| **Plan**   | Detection within 15 seconds |
| **Wish**   | Detection within 5 seconds |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Agent |
| **Stimulus**       | Becomes unresponsive during a run |
| **Environment**    | Parallel fan-out phase |
| **Artifact**       | Orchestrator heartbeat monitor |
| **Response**       | Orchestrator detects absence of heartbeat and marks the agent as ERROR |
| **Response Measure** | Orchestrator detects agent heartbeat failure within 30 seconds; run transitions to an error state with the unresponsive agent identified; no run hangs indefinitely |

## Verification

- **Automated**: TBD
- **Manual**: Kill an agent mid-run and verify orchestrator detects failure within 30 seconds
