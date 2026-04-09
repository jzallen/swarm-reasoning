---
id: NFR-017
title: "Full Local Stack Runs via a Single Docker Compose Command"
status: accepted
category: portability
subcategory: installability
priority: must
components: [docker-compose, all-containers]
adrs: []
tests: []
date: 2026-04-09
---

# NFR-017: Full Local Stack Runs via a Single Docker Compose Command

## Context

Developer onboarding friction must be minimized. A single-command setup ensures new contributors can run the full system without manual service orchestration or undocumented setup steps.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Number of commands required to start the full stack from a fresh clone |
| **Meter**  | Count of manual steps from clone to accepting a test claim |
| **Must**   | One command (`docker compose up`); test claim reaches PUBLISHED within 5 minutes |
| **Plan**   | One command; test claim reaches PUBLISHED within 3 minutes |
| **Wish**   | One command; test claim reaches PUBLISHED within 2 minutes |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Developer |
| **Stimulus**       | Clones the repository on a machine with Docker installed |
| **Environment**    | macOS or Linux, Docker 24+, 16GB RAM |
| **Artifact**       | Docker Compose stack (all 13 containers) |
| **Response**       | All 13 containers start and the system accepts a test claim submission |
| **Response Measure** | `docker compose -f docs/infrastructure/docker-compose.yml up` completes without error and a test claim reaches PUBLISHED state within 5 minutes of first startup |

## Verification

- **Automated**: TBD
- **Manual**: Fresh clone, run docker compose up, submit test claim, verify PUBLISHED state
