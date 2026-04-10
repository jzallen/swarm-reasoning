---
id: NFR-010
title: "Agent Service Internal-Network-Only"
status: accepted
category: security
subcategory: confidentiality
priority: must
components: [agent-service, temporal-server, vpc-network]
adrs: [ADR-016, ADR-020]
tests: []
date: 2026-04-09
---

# NFR-010: Agent Service Internal-Network-Only

## Context

Agent services (Temporal workers) process sensitive claim data and interact with LLMs. If reachable from outside the VPC or Docker network, an attacker could directly invoke agent logic, manipulate agent state, or exfiltrate observations. Only the NestJS backend API should be externally accessible via the Application Load Balancer.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Number of agent service ports exposed outside VPC |
| **Meter**  | Network scan from outside VPC targeting agent service and Temporal server ports |
| **Must**   | Zero agent service ports reachable from outside VPC |
| **Plan**   | Zero agent service ports reachable from outside VPC |
| **Wish**   | Zero agent service ports reachable from outside VPC |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | External actor |
| **Stimulus**       | Attempts to connect to an agent service or Temporal server port |
| **Environment**    | Production AWS VPC (ECS Fargate deployment) |
| **Artifact**       | Agent service ports, Temporal server ports |
| **Response**       | Connection is refused; only the NestJS backend API is reachable via ALB |
| **Response Measure** | Agent service and Temporal server ports are not exposed outside the VPC; verified by network scan from outside the VPC |

## Verification

- **Automated**: TBD
- **Manual**: Run nmap from outside the VPC against agent service and Temporal ports and verify all connections refused
