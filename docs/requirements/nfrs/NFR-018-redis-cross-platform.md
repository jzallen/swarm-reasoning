---
id: NFR-018
title: "Redis Runs in Docker on macOS and Linux"
status: accepted
category: portability
subcategory: adaptability
priority: must
components: [redis, docker-compose]
adrs: []
tests: []
date: 2026-04-09
---

# NFR-018: Redis Runs in Docker on macOS and Linux

## Context

The team develops on both macOS and Linux. Redis must start reliably on both platforms to avoid platform-specific onboarding issues.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Successful Redis container start across platforms |
| **Meter**  | `redis-cli ping` returning PONG after container start |
| **Must**   | Redis starts and responds to PING on both macOS and Linux |
| **Plan**   | Redis starts and responds to PING on both macOS and Linux |
| **Wish**   | Redis starts and responds to PING on macOS, Linux, and Windows WSL2 |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Developer |
| **Stimulus**       | Attempts to run the Redis container |
| **Environment**    | macOS with Docker Desktop or Linux with Docker Engine |
| **Artifact**       | Redis Docker container |
| **Response**       | Redis starts and accepts connections |
| **Response Measure** | Redis Docker container starts without error; confirmed by `redis-cli ping` returning PONG |

## Verification

- **Automated**: TBD
- **Manual**: Start Redis container on macOS and Linux, verify PONG response
