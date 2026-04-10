---
id: NFR-028
title: "SSE Progress Event Latency"
status: accepted
category: performance
subcategory: time-behaviour
priority: must
components: [backend-api, redis]
adrs: [ADR-018]
tests: []
date: 2026-04-09
---

# NFR-028: SSE Progress Event Latency

## Context

Users watch agent progress in real-time via Server-Sent Events (SSE). The delay between an agent publishing a progress message to Redis and the corresponding SSE event reaching the browser must be bounded to maintain a responsive user experience.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Elapsed time from Redis XADD to SSE event receipt in the browser |
| **Meter**  | Instrumented timer measuring delta between Redis publish timestamp and browser SSE event callback timestamp |
| **Must**   | < 2000 ms |
| **Plan**   | < 1000 ms |
| **Wish**   | < 500 ms |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Agent worker |
| **Stimulus**       | Agent publishes a progress message to Redis Streams |
| **Environment**    | Normal operation, SSE connection active between browser and backend-api |
| **Artifact**       | Backend-api SSE relay, Redis Streams |
| **Response**       | Backend reads the progress message from Redis and relays it as an SSE event to the browser |
| **Response Measure** | Elapsed time from Redis XADD to SSE event receipt in the browser is under 2000 ms |

## Verification

- **Automated**: TBD
- **Manual**: Instrument Redis publish and browser SSE receipt timestamps during a run and measure the delta
