---
id: NFR-024
title: "Run Status Is Queryable at Any Point During Processing"
status: accepted
category: observability
subcategory: operability
priority: must
components: [backend-api, orchestrator]
adrs: [ADR-016]
tests: []
date: 2026-04-09
---

# NFR-024: Run Status Is Queryable at Any Point During Processing

## Context

Operators need real-time visibility into run progress. If status is only available after completion, operators cannot detect stalled runs or make informed decisions during processing.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Response time and availability of GET /runs/{run_id} during active runs |
| **Meter**  | API response time measurement at each lifecycle state |
| **Must**   | Responds within 500 ms with current session status, agents complete, agents pending; available at all lifecycle states |
| **Plan**   | Responds within 200 ms |
| **Wish**   | Responds within 100 ms |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Operator |
| **Stimulus**       | Polls GET /sessions/{id} during an active run |
| **Environment**    | Run in ANALYZING state |
| **Artifact**       | Backend API |
| **Response**       | API returns current status and completion register summary |
| **Response Measure** | GET /sessions/{id} responds within 500 ms with current status, number of agents complete, and number of agents pending; available at all lifecycle states |

## Verification

- **Automated**: TBD
- **Manual**: Poll the run status endpoint during each lifecycle state and measure response time
