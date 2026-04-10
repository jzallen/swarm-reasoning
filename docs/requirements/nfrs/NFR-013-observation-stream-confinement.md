---
id: NFR-013
title: "Observation Streams Are Confined to the Internal Network"
status: accepted
category: security
subcategory: confidentiality
priority: must
components: [redis, vpc-network]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-013: Observation Streams Are Confined to the Internal Network

## Context

Observation streams contain claim text and intermediate analysis. In production (AWS), Redis traffic must not leave the VPC. In local development, Redis traffic must remain within the Docker bridge network. If Redis traffic is observable outside these boundaries, sensitive claim data could be intercepted.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Redis protocol traffic observable outside VPC (production) or Docker bridge network (local dev) |
| **Meter**  | Packet capture on VPC boundary / host network interface |
| **Must**   | Zero Redis protocol packets crossing VPC boundary (production) or host network interface (local dev) |
| **Plan**   | Zero Redis protocol packets crossing VPC boundary (production) or host network interface (local dev) |
| **Wish**   | Zero Redis protocol packets crossing VPC boundary (production) or host network interface (local dev) |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Agent |
| **Stimulus**       | An observation stream containing claim text is being published to Redis |
| **Environment**    | Normal operation; production AWS VPC or local Docker bridge network |
| **Artifact**       | Redis, VPC security groups (production) / Docker bridge network (local dev) |
| **Response**       | Redis traffic is transmitted only within the VPC (production) or Docker bridge network (local dev) |
| **Response Measure** | No Redis protocol traffic is observable outside the VPC (production) or Docker bridge network (local dev); verified by packet capture on VPC boundary or host network interface |

## Verification

- **Automated**: TBD
- **Manual**: Run tcpdump on VPC boundary (production) or host interface (local dev) during a run and verify no Redis protocol traffic crosses the boundary
