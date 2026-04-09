---
id: NFR-022
title: "Every Published Verdict Has a Traceable Audit Log"
status: accepted
category: auditability
subcategory: accountability
priority: must
components: [redis, synthesizer, consumer-api]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-022: Every Published Verdict Has a Traceable Audit Log

## Context

Published verdicts may be disputed. Analysts must be able to trace any verdict back to the specific observations that determined it, with attribution to the originating agent. Without this, the system lacks accountability.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Number of distinct agents with attributed observations per published verdict |
| **Meter**  | Count distinct agent fields in observation streams referenced by each verdict |
| **Must**   | >= 8 distinct agents per published verdict |
| **Plan**   | >= 9 distinct agents per published verdict |
| **Wish**   | 10 distinct agents per published verdict |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Analyst |
| **Stimulus**       | Disputes a published verdict for a run |
| **Environment**    | Post-publication |
| **Artifact**       | Redis Streams observation log |
| **Response**       | The analyst retrieves the observation streams and identifies the specific observations that determined the verdict |
| **Response Measure** | Every published verdict references observation streams in Redis that contain observations from at least 8 distinct agents with agent field attribution |

## Verification

- **Automated**: TBD
- **Manual**: For a published verdict, query observation streams and count distinct agents
