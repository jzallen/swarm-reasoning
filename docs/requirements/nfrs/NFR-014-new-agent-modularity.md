---
id: NFR-014
title: "New Agent Can Be Added Without Modifying Existing Agents"
status: accepted
category: maintainability
subcategory: modifiability
priority: must
components: [orchestrator, all-agents]
adrs: [ADR-016]
tests: []
date: 2026-04-09
---

# NFR-014: New Agent Can Be Added Without Modifying Existing Agents

## Context

The swarm architecture must scale to new specialist agents (e.g., scientific literature, geopolitical) without coupling changes across existing agents. This keeps the system modular and reduces regression risk.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Number of existing agent files modified when adding a new agent |
| **Meter**  | git diff after adding a new agent |
| **Must**   | Zero existing agent files modified |
| **Plan**   | Zero existing agent files modified |
| **Wish**   | Zero existing agent files modified |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Developer |
| **Stimulus**       | A new specialist agent (e.g., a scientific literature agent) is added to the system |
| **Environment**    | Development |
| **Artifact**       | Orchestrator DAG, observation code registry |
| **Response**       | The new agent is registered in the orchestrator DAG and observation code registry; no existing agent code is modified |
| **Response Measure** | Zero existing agent files modified when adding a new agent, verified by git diff |

## Verification

- **Automated**: TBD
- **Manual**: Add a stub agent and verify via git diff that no existing agent files were changed
