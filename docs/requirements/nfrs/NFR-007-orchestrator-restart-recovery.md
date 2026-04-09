---
id: NFR-007
title: "Orchestrator Restart Recovery"
status: accepted
category: reliability
subcategory: recoverability
priority: must
components: [orchestrator, redis]
adrs: [ADR-010]
tests: []
date: 2026-04-09
---

# NFR-007: Orchestrator Restart Recovery

## Context

A stateless orchestrator that crashes must reconstruct run state from Redis Streams on restart. Without this, partial runs would be abandoned, wasting compute and leaving claims unresolved.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Time from orchestrator restart to correct run resumption |
| **Meter**  | Timer from process start to successful state reconstruction and resumed dispatching |
| **Must**   | Run resumes within 30 seconds, no duplicate dispatches, no data loss |
| **Plan**   | Run resumes within 15 seconds |
| **Wish**   | Run resumes within 5 seconds |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Infrastructure (process crash) |
| **Stimulus**       | Orchestrator process terminates unexpectedly during an active run |
| **Environment**    | Run in ANALYZING state with partial agent completion |
| **Artifact**       | Orchestrator |
| **Response**       | Orchestrator restarts and reconstructs completion state by scanning Redis Streams for STOP messages |
| **Response Measure** | Run resumes correctly within 30 seconds of orchestrator restart, with no duplicate agent dispatches and no data loss in Redis Streams |

## Verification

- **Automated**: TBD
- **Manual**: Kill orchestrator during ANALYZING state, restart, and verify run completes correctly
