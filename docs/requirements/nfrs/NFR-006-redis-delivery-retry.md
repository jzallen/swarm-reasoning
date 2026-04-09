---
id: NFR-006
title: "Redis Streams Delivery Retry Behaviour"
status: accepted
category: reliability
subcategory: fault-tolerance
priority: must
components: [orchestrator, redis]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-006: Redis Streams Delivery Retry Behaviour

## Context

If the orchestrator crashes mid-processing, unacknowledged Redis Streams entries must remain reclaimable. Without this guarantee, observations could be silently lost.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Time to reclaim and process unacknowledged entries after orchestrator recovery |
| **Meter**  | Timer from orchestrator restart to successful processing of all pending entries |
| **Must**   | All unacknowledged entries reclaimed within 30 seconds of recovery |
| **Plan**   | All unacknowledged entries reclaimed within 15 seconds of recovery |
| **Wish**   | All unacknowledged entries reclaimed within 5 seconds of recovery |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Orchestrator |
| **Stimulus**       | Fails to acknowledge a stream entry (consumer crashes mid-processing) |
| **Environment**    | Transient orchestrator error |
| **Artifact**       | Redis Streams pending entries list |
| **Response**       | Unacknowledged entries remain in the pending entries list and are reclaimable via XPENDING/XCLAIM |
| **Response Measure** | All unacknowledged entries are reclaimed and processed within 30 seconds of orchestrator recovery |

## Verification

- **Automated**: TBD
- **Manual**: Kill orchestrator mid-run, restart, and verify pending entries are reclaimed
