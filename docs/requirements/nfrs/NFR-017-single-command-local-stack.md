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
| **Must**   | One command (`docker compose up`); test claim reaches completed within 5 minutes |
| **Plan**   | One command; test claim reaches completed within 3 minutes |
| **Wish**   | One command; test claim reaches completed within 2 minutes |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Developer |
| **Stimulus**       | Clones the repository on a machine with Docker installed |
| **Environment**    | macOS or Linux, Docker 24+, 16GB RAM |
| **Artifact**       | Docker Compose stack (all 8 services) |
| **Response**       | All 8 services start and the system accepts a test claim submission |
| **Response Measure** | `docker compose up` completes without error and a test claim reaches completed state within 5 minutes of first startup |

## Verification

- **Automated**: TBD
- **Manual**: Fresh clone, run docker compose up, submit test claim, verify completed state
