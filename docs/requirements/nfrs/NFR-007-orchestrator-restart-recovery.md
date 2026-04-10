---
id: NFR-007
title: "Orchestrator Restart Recovery"
status: accepted
category: reliability
subcategory: recoverability
priority: must
components: [orchestrator, temporal-server]
adrs: [ADR-016]
tests: []
date: 2026-04-09
---

# NFR-007: Orchestrator Restart Recovery

## Context

With Temporal as the orchestration engine, workflow state is durably persisted in Temporal's event history. When the orchestrator process crashes or restarts, Temporal automatically replays the workflow from its event history to reconstruct state. This eliminates the need for manual state reconstruction from Redis Streams.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Time from orchestrator restart to correct run resumption |
| **Meter**  | Timer from process start to successful workflow replay and resumed dispatching |
| **Must**   | Automatic recovery via Temporal workflow replay, no duplicate dispatches, no data loss |
| **Plan**   | Run resumes within 10 seconds |
| **Wish**   | Run resumes within 5 seconds |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Infrastructure (process crash) |
| **Stimulus**       | Orchestrator process terminates unexpectedly during an active run |
| **Environment**    | Run in ANALYZING state with partial agent completion |
| **Artifact**       | Orchestrator, Temporal server |
| **Response**       | Temporal replays the workflow from its event history, reconstructing state and resuming from where execution left off |
| **Response Measure** | Run resumes automatically via Temporal replay with no duplicate agent dispatches and no data loss |

## Verification

- **Automated**: TBD
- **Manual**: Kill orchestrator during ANALYZING state, restart, and verify Temporal replays the workflow and run completes correctly
