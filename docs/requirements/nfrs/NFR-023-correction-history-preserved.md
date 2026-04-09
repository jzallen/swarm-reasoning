---
id: NFR-023
title: "Correction History Is Preserved in the Audit Log"
status: accepted
category: auditability
subcategory: non-repudiation
priority: must
components: [redis, all-agents]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-023: Correction History Is Preserved in the Audit Log

## Context

When an agent emits a C-status correction overriding a prior F-status observation, both the original and the correction must coexist in the stream. Losing the original would destroy the epistemic audit trail.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Number of original F observations absent when a corresponding C observation exists |
| **Meter**  | Stream scan across validation corpus |
| **Must**   | Zero missing original F observations |
| **Plan**   | Zero missing original F observations |
| **Wish**   | Zero missing original F observations |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Agent |
| **Stimulus**       | Emits a C-status correction overriding a prior F-status observation |
| **Environment**    | Any run |
| **Artifact**       | Redis Streams |
| **Response**       | Both the original F observation and the correction C observation are present in the Redis Stream |
| **Response Measure** | Zero original F observations are absent from the stream when a corresponding C observation exists; verified across the validation corpus |

## Verification

- **Automated**: TBD
- **Manual**: Trigger a correction and verify both F and C observations are present in the stream
