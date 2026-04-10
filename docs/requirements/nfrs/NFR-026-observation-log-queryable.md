---
id: NFR-026
title: "Observation Log Is Queryable for Post-Run Analysis"
status: accepted
category: observability
subcategory: analysability
priority: must
components: [redis, backend-api]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-026: Observation Log Is Queryable for Post-Run Analysis

## Context

Data analysts need to query observations across completed runs for pattern analysis, quality monitoring, and model tuning. Query performance must be acceptable even as the corpus grows.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Query time for filtered XRANGE scan across completed runs |
| **Meter**  | XRANGE scan filtered by observation code across 50 completed runs |
| **Must**   | Completes in under 2 seconds for 50 completed runs |
| **Plan**   | Completes in under 1 second for 50 completed runs |
| **Wish**   | Completes in under 500 ms for 50 completed runs |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Data analyst |
| **Stimulus**       | Wants to retrieve all BLINDSPOT_SCORE observations above 0.7 across all published runs |
| **Environment**    | Post-publication, Redis Streams loaded with completed runs |
| **Artifact**       | Redis Streams |
| **Response**       | Query returns matching observations with run_id attribution |
| **Response Measure** | XRANGE scan across run streams filtered by code = BLINDSPOT_SCORE completes in under 2 seconds for a corpus of 50 completed runs |

## Verification

- **Automated**: TBD
- **Manual**: Run XRANGE query against 50 completed runs and measure response time
