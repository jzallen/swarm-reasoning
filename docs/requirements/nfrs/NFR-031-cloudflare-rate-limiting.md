---
id: NFR-031
title: "Cloudflare Rate Limiting"
status: accepted
category: security
subcategory: abuse-prevention
priority: must
components: [cloudflare, backend-api]
adrs: [ADR-020]
tests: []
date: 2026-04-09
---

# NFR-031: Cloudflare Rate Limiting

## Context

The claim submission endpoint triggers expensive LLM processing across multiple agents. Without rate limiting, a single IP could exhaust system resources or incur excessive API costs. Cloudflare edge rate limiting provides the first line of defense against abuse.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Maximum claim submissions per IP per minute |
| **Meter**  | Cloudflare rate limiting rule counter per source IP |
| **Must**   | <= 10 submissions per IP per minute |
| **Plan**   | <= 5 submissions per IP per minute |
| **Wish**   | <= 3 submissions per IP per minute |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | External user or automated client |
| **Stimulus**       | Submits claims at a rate exceeding the configured threshold |
| **Environment**    | Normal operation, Cloudflare edge proxy active |
| **Artifact**       | Cloudflare rate limiting rule, backend-api |
| **Response**       | Cloudflare blocks excess requests with HTTP 429 before they reach the backend |
| **Response Measure** | No more than 10 claim submissions per IP per minute reach the backend |

## Verification

- **Automated**: TBD
- **Manual**: Send rapid claim submissions from a single IP and verify HTTP 429 responses after threshold
