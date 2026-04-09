---
id: NFR-003
title: "MCP Round-Trip Latency"
status: accepted
category: performance
subcategory: time-behaviour
priority: must
components: [orchestrator, mcp-servers]
adrs: [ADR-009]
tests: []
date: 2026-04-09
---

# NFR-003: MCP Round-Trip Latency

## Context

The orchestrator uses MCP tool calls to query agent state. High MCP latency compounds across multiple calls per run phase, directly inflating end-to-end latency.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | P99 round-trip latency for get_observations MCP tool call |
| **Meter**  | Instrumented timer on orchestrator MCP client calls returning < 100 observations |
| **Must**   | P99 < 500 ms |
| **Plan**   | P99 < 300 ms |
| **Wish**   | P99 < 100 ms |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Orchestrator |
| **Stimulus**       | Issues a get_observations MCP tool call to a subagent |
| **Environment**    | Normal operation, agent healthy, observations present in Redis Streams |
| **Artifact**       | MCP server on target agent |
| **Response**       | Agent MCP server returns observations |
| **Response Measure** | P99 latency under 500 ms for queries returning fewer than 100 observations |

## Verification

- **Automated**: TBD
- **Manual**: Load-test MCP calls and measure P99 latency
