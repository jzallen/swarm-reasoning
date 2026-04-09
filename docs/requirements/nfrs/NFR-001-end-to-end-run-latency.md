---
id: NFR-001
title: "End-to-End Run Latency"
status: accepted
category: performance
subcategory: time-behaviour
priority: must
components: [orchestrator, consumer-api]
adrs: [ADR-009, ADR-010]
tests: []
date: 2026-04-09
---

# NFR-001: End-to-End Run Latency

## Context

The system must deliver verdicts within a bounded time window so that operators and downstream consumers receive timely fact-check results. The parallel fan-out phase and external API calls are the primary latency drivers.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Elapsed wall-clock time from POST acceptance to PUBLISHED status |
| **Meter**  | Timer from HTTP 202 response to PUBLISHED state transition |
| **Must**   | <= 120 seconds |
| **Plan**   | <= 90 seconds |
| **Wish**   | <= 60 seconds |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Operator |
| **Stimulus**       | Submits a check-worthy claim via POST /claims |
| **Environment**    | Normal operation, all 10 agents healthy, external APIs reachable |
| **Artifact**       | Orchestrator, all agents, consumer-api |
| **Response**       | System processes the claim to PUBLISHED state |
| **Response Measure** | Elapsed time from POST acceptance to PUBLISHED status is under 120 seconds |

## Verification

- **Automated**: TBD
- **Manual**: Submit a claim and measure elapsed time to PUBLISHED state
