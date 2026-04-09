---
id: NFR-004
title: "Observation Publish Throughput"
status: accepted
category: performance
subcategory: resource-utilisation
priority: must
components: [redis, coverage-left, coverage-center, coverage-right, domain-evidence, blindspot-detector]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-004: Observation Publish Throughput

## Context

During parallel fan-out, five agents write observations concurrently to Redis Streams. The system must sustain this throughput without producing duplicate sequence numbers, which would indicate data corruption.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Duplicate sequence numbers per agent stream |
| **Meter**  | Sequence number uniqueness check across 1000 consecutive load-test runs |
| **Must**   | Zero duplicates across 1000 runs |
| **Plan**   | Zero duplicates across 5000 runs |
| **Wish**   | Zero duplicates across 10000 runs |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Multiple agents |
| **Stimulus**       | Publish observations concurrently during parallel fan-out |
| **Environment**    | Peak load -- 5 agents writing concurrently to Redis Streams |
| **Artifact**       | Redis Streams |
| **Response**       | All observations are persisted correctly with unique sequence numbers per stream |
| **Response Measure** | Zero duplicate sequence numbers within any agent stream across 1000 consecutive runs in load testing |

## Verification

- **Automated**: TBD
- **Manual**: Run load test and verify sequence number uniqueness per stream
