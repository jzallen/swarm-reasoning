---
id: NFR-029
title: "Session TTL and Cleanup"
status: accepted
category: maintainability
subcategory: resource-management
priority: must
components: [backend-api, s3, postgresql]
adrs: [ADR-019]
tests: []
date: 2026-04-09
---

# NFR-029: Session TTL and Cleanup

## Context

Sessions are ephemeral with a 3-day retention period. Static HTML snapshots, database rows, and Redis stream data must be cleaned up after expiry to prevent unbounded storage growth across S3, PostgreSQL, and Redis.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Age of oldest expired session still present in the system |
| **Meter**  | Periodic scan comparing session expiry timestamps against current time |
| **Must**   | All expired sessions cleaned within 24 hours of expiry |
| **Plan**   | All expired sessions cleaned within 6 hours of expiry |
| **Wish**   | All expired sessions cleaned within 1 hour of expiry |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | System (scheduled cleanup) |
| **Stimulus**       | A session reaches its 3-day TTL expiry |
| **Environment**    | Normal operation |
| **Artifact**       | Backend-api cleanup job, PostgreSQL rows, S3 static HTML snapshots, Redis stream data |
| **Response**       | Cleanup job removes all associated resources (database rows, S3 objects, Redis streams) for the expired session |
| **Response Measure** | All resources for expired sessions are removed within 24 hours of expiry |

## Verification

- **Automated**: TBD
- **Manual**: Create a session, wait for TTL expiry, and verify all associated resources are cleaned up within the specified window
