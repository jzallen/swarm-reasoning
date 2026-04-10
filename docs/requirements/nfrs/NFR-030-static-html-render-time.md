---
id: NFR-030
title: "Static HTML Verdict Render Time"
status: accepted
category: performance
subcategory: time-behaviour
priority: must
components: [backend-api, s3]
adrs: [ADR-019]
tests: []
date: 2026-04-09
---

# NFR-030: Static HTML Verdict Render Time

## Context

After the synthesizer agent emits a verdict, the backend renders a static HTML snapshot and writes it to S3. This rendering must not significantly delay the final SSE verdict event sent to the user.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Elapsed time from verdict observation to static HTML file written to S3 |
| **Meter**  | Instrumented timer measuring delta between verdict observation timestamp and S3 PutObject completion |
| **Must**   | < 5000 ms |
| **Plan**   | < 3000 ms |
| **Wish**   | < 1000 ms |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Synthesizer agent |
| **Stimulus**       | Synthesizer emits a verdict observation |
| **Environment**    | Normal operation, S3 reachable |
| **Artifact**       | Backend-api HTML renderer, S3 bucket |
| **Response**       | Backend renders the verdict as a static HTML snapshot and writes it to S3 |
| **Response Measure** | Elapsed time from verdict observation to static HTML file written to S3 is under 5000 ms |

## Verification

- **Automated**: TBD
- **Manual**: Trigger a verdict and measure elapsed time from verdict observation to S3 object creation
