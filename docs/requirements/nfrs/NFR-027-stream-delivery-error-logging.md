---
id: NFR-027
title: "Stream Delivery Errors Surface in the Run Error Log"
status: accepted
category: observability
subcategory: operability
priority: must
components: [all-agents, orchestrator, redis]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-027: Stream Delivery Errors Surface in the Run Error Log

## Context

Silent observation publish failures would cause missing signals in synthesis, producing unreliable verdicts. Every publish failure must be logged with enough context for diagnosis.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Percentage of stream publish failures that appear in the run error log |
| **Meter**  | Inject deliberate Redis failures and measure error log completeness |
| **Must**   | 100% of failures logged within 5 seconds of occurrence |
| **Plan**   | 100% of failures logged within 2 seconds of occurrence |
| **Wish**   | 100% of failures logged within 1 second of occurrence |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Agent |
| **Stimulus**       | An observation fails to publish to Redis Streams (e.g., Redis unreachable) |
| **Environment**    | Any phase of a run |
| **Artifact**       | Run error log |
| **Response**       | The error is recorded in the run error log with run_id, agent, error type, and timestamp |
| **Response Measure** | 100% of stream publish failures appear in the run error log within 5 seconds of occurrence; verified by injecting deliberate Redis failures in integration tests |

## Verification

- **Automated**: TBD
- **Manual**: Inject Redis failures during a run and verify all errors appear in the run error log
