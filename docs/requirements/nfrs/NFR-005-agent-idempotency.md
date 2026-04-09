---
id: NFR-005
title: "Agent Idempotency"
status: accepted
category: reliability
subcategory: fault-tolerance
priority: must
components: [orchestrator, all-agents]
adrs: [ADR-003, ADR-010]
tests: []
date: 2026-04-09
---

# NFR-005: Agent Idempotency

## Context

Network timeouts or orchestrator retries can cause duplicate task dispatches. Agents must detect and ignore duplicates to prevent inflated observation counts that would corrupt synthesis.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Observation count delta after duplicate dispatch |
| **Meter**  | Compare observation count for a run_id before and after a duplicate dispatch |
| **Must**   | Zero additional observations from duplicate dispatch |
| **Plan**   | Zero additional observations from duplicate dispatch |
| **Wish**   | Zero additional observations from duplicate dispatch |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Orchestrator |
| **Stimulus**       | Dispatches the same agent task twice for the same run_id (e.g., due to timeout and retry) |
| **Environment**    | Any agent |
| **Artifact**       | Target agent |
| **Response**       | Agent detects duplicate dispatch and does not publish additional observations |
| **Response Measure** | Observation count for the run is identical before and after the duplicate dispatch |

## Verification

- **Automated**: TBD
- **Manual**: Force a duplicate dispatch and verify observation count is unchanged
