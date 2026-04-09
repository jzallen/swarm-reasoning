---
id: NFR-012
title: "External API Responses Are Validated Before Observation Write"
status: accepted
category: security
subcategory: integrity
priority: must
components: [claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence]
adrs: [ADR-004]
tests: []
date: 2026-04-09
---

# NFR-012: External API Responses Are Validated Before Observation Write

## Context

External APIs (NewsAPI, MBFC, Google Fact Check Tools) may return malformed or unexpectedly large responses. Without validation, invalid data could propagate into the observation log and corrupt downstream synthesis.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Number of invalid observations published from malformed API responses |
| **Meter**  | Integration tests injecting malformed API responses |
| **Must**   | Zero invalid observations from malformed responses |
| **Plan**   | Zero invalid observations from malformed responses |
| **Wish**   | Zero invalid observations from malformed responses |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | External API (NewsAPI, MBFC, GFCT) |
| **Stimulus**       | Returns a malformed or unexpectedly large response |
| **Environment**    | Agent executing a coverage or domain evidence task |
| **Artifact**       | Agent tool layer |
| **Response**       | Agent validates the response before passing it to the tool layer for observation publishing |
| **Response Measure** | No malformed external API response causes an invalid observation to be published to Redis Streams; verified by injecting malformed responses in integration tests |

## Verification

- **Automated**: TBD
- **Manual**: Inject malformed API responses and verify no invalid observations are published
