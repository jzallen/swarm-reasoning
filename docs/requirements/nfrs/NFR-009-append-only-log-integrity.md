---
id: NFR-009
title: "Append-Only Log Integrity"
status: accepted
category: reliability
subcategory: integrity
priority: must
components: [redis, all-agents, orchestrator]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-009: Append-Only Log Integrity

## Context

The observation log in Redis Streams is the authoritative record. If entries could be modified or deleted after write, audit trails would be unreliable and verdict provenance would be compromised.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Number of observations modified or deleted after initial write |
| **Meter**  | Compare Redis Stream entry counts before and after a full run |
| **Must**   | Zero modifications or deletions of existing observations |
| **Plan**   | Zero modifications or deletions of existing observations |
| **Wish**   | Zero modifications or deletions of existing observations |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Any process (agent, orchestrator, test harness) |
| **Stimulus**       | Attempts to modify or delete an existing observation |
| **Environment**    | Any |
| **Artifact**       | Redis Streams |
| **Response**       | The operation is rejected (Redis Streams entries are immutable once written) |
| **Response Measure** | No existing observation is modified or deleted after initial write; verified by comparing Redis Stream entry counts before and after a full run |

## Verification

- **Automated**: TBD
- **Manual**: Attempt XDEL on an existing entry and verify rejection; compare entry counts pre/post run
