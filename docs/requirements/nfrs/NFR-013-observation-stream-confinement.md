---
id: NFR-013
title: "Observation Streams Are Confined to the Internal Docker Network"
status: accepted
category: security
subcategory: confidentiality
priority: must
components: [redis, docker-network]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-013: Observation Streams Are Confined to the Internal Docker Network

## Context

Observation streams contain claim text and intermediate analysis. If Redis traffic is observable outside the Docker bridge network, sensitive claim data could be intercepted.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Redis protocol traffic observable outside Docker bridge network |
| **Meter**  | Packet capture on host network interface |
| **Must**   | Zero Redis protocol packets on host network interface |
| **Plan**   | Zero Redis protocol packets on host network interface |
| **Wish**   | Zero Redis protocol packets on host network interface |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Agent |
| **Stimulus**       | An observation stream containing claim text is being published to Redis |
| **Environment**    | Normal operation |
| **Artifact**       | Redis, Docker bridge network |
| **Response**       | Redis traffic is transmitted only on the internal Docker network |
| **Response Measure** | No Redis protocol traffic is observable outside the Docker bridge network; verified by packet capture on the host network interface |

## Verification

- **Automated**: TBD
- **Manual**: Run tcpdump on host interface during a run and verify no Redis protocol traffic
