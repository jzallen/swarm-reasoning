---
id: NFR-008
title: "Redis Streams Write Isolation for Concurrent Observations"
status: accepted
category: reliability
subcategory: fault-tolerance
priority: must
components: [redis, all-agents]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-008: Redis Streams Write Isolation for Concurrent Observations

## Context

During parallel fan-out, five agents write concurrently. Per-agent stream keys (`reasoning:{runId}:{agent}`) eliminate cross-stream write conflicts by design. This NFR codifies that isolation guarantee.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Observation collisions across concurrent agent writes |
| **Meter**  | Per-stream sequence number integrity check across all runs |
| **Must**   | Zero observation collisions across all runs |
| **Plan**   | Zero observation collisions across all runs |
| **Wish**   | Zero observation collisions across all runs |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Parallel fan-out agents |
| **Stimulus**       | Five agents publish observations concurrently to their respective streams |
| **Environment**    | Parallel fan-out phase |
| **Artifact**       | Redis Streams (per-agent stream keys) |
| **Response**       | Each agent writes to its own stream key; no cross-stream conflicts are possible |
| **Response Measure** | Zero observation collisions across all runs; verified by per-stream sequence number integrity checks |

## Verification

- **Automated**: TBD
- **Manual**: Run concurrent fan-out and verify per-stream sequence integrity
