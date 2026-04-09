---
id: NFR-016
title: "Transport Backend Is Swappable via Configuration"
status: accepted
category: maintainability
subcategory: modifiability
priority: must
components: [orchestrator, all-agents, redis]
adrs: [ADR-003]
tests: []
date: 2026-04-09
---

# NFR-016: Transport Backend Is Swappable via Configuration

## Context

Coupling agents to a specific transport (Redis Streams) limits future flexibility. A pluggable transport interface allows switching to Kafka or other backends without modifying agent or orchestrator business logic.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Number of agent or orchestrator source files modified to swap transport backend |
| **Meter**  | git diff after swapping from Redis to an alternative backend |
| **Must**   | Zero agent or orchestrator code files modified; only implementation class and config change |
| **Plan**   | Zero agent or orchestrator code files modified |
| **Wish**   | Zero agent or orchestrator code files modified |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Engineering team |
| **Stimulus**       | Decides to switch from Redis Streams to Kafka for the observation transport |
| **Environment**    | Development |
| **Artifact**       | ReasoningStream interface, STREAM_BACKEND config |
| **Response**       | A new KafkaReasoningStream implementation is provided; the STREAM_BACKEND config variable is changed from redis to kafka |
| **Response Measure** | No agent code or orchestrator code is modified; only the ReasoningStream implementation and configuration change; verified by running the acceptance test suite against both backends |

## Verification

- **Automated**: Run acceptance test suite against both Redis and alternative backend
- **Manual**: Swap STREAM_BACKEND config and verify all tests pass
