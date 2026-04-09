---
id: NFR-015
title: "New Observation Code Can Be Added Without Schema Migration"
status: accepted
category: maintainability
subcategory: modifiability
priority: must
components: [orchestrator, redis]
adrs: [ADR-003, ADR-004]
tests: []
date: 2026-04-09
---

# NFR-015: New Observation Code Can Be Added Without Schema Migration

## Context

The observation code registry must be extensible at runtime. Requiring schema migrations or Redis restarts to add a code would slow iteration and introduce downtime risk.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Steps required to make a new observation code usable |
| **Meter**  | Count of migration scripts or service restarts required |
| **Must**   | New code usable within one orchestrator restart; no migration script required |
| **Plan**   | New code usable within one orchestrator restart; no migration script required |
| **Wish**   | New code usable with zero restarts (hot reload) |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Developer |
| **Stimulus**       | A new observation code is added to obx-code-registry.json |
| **Environment**    | Development |
| **Artifact**       | Observation code registry, orchestrator |
| **Response**       | The new code is available to agents at runtime without restarting Redis or running a migration script |
| **Response Measure** | New code is usable within one orchestrator restart; no migration script required |

## Verification

- **Automated**: TBD
- **Manual**: Add a code to the registry, restart orchestrator, and verify an agent can publish with it
