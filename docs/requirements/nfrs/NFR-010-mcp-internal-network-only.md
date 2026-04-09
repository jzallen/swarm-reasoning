---
id: NFR-010
title: "MCP Connections Are Internal-Network-Only"
status: accepted
category: security
subcategory: confidentiality
priority: must
components: [mcp-servers, docker-network]
adrs: [ADR-009]
tests: []
date: 2026-04-09
---

# NFR-010: MCP Connections Are Internal-Network-Only

## Context

MCP servers expose agent control interfaces. If reachable from outside the Docker network, an attacker could issue tool calls to manipulate agent state or exfiltrate observations.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Number of MCP server ports exposed outside Docker internal network |
| **Meter**  | Network scan from host targeting agent MCP ports |
| **Must**   | Zero MCP ports reachable from outside Docker network |
| **Plan**   | Zero MCP ports reachable from outside Docker network |
| **Wish**   | Zero MCP ports reachable from outside Docker network |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | External actor |
| **Stimulus**       | Attempts to connect to a subagent MCP server |
| **Environment**    | Production Docker network |
| **Artifact**       | Agent MCP server ports |
| **Response**       | Connection is refused |
| **Response Measure** | Agent MCP server ports are not exposed outside the Docker internal network; verified by network scan from outside the Docker network |

## Verification

- **Automated**: TBD
- **Manual**: Run nmap from host against MCP ports and verify all connections refused
