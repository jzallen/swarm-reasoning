---
id: NFR-011
title: "PII Sanitization Before LLM Calls"
status: accepted
category: security
subcategory: confidentiality
priority: must
components: [ingestion-agent, all-agents]
adrs: []
tests: []
date: 2026-04-09
---

# NFR-011: PII Sanitization Before LLM Calls

## Context

Claims may contain personally identifiable information. Sending raw PII to external LLM providers creates privacy and compliance risks. Sanitization before LLM calls limits data exposure.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Count of raw PII fields (SSN, DOB, financial identifiers) in LLM prompt payloads |
| **Meter**  | Log analysis of LLM prompt payloads across the validation corpus |
| **Must**   | Zero raw PII fields in LLM prompt payloads |
| **Plan**   | Zero raw PII fields in LLM prompt payloads |
| **Wish**   | Zero raw PII fields in LLM prompt payloads |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Operator |
| **Stimulus**       | A claim text containing a named individual and a date of birth is submitted |
| **Environment**    | Normal operation |
| **Artifact**       | LLM prompt construction layer |
| **Response**       | The prompt sent to the LLM provider does not contain the raw date of birth |
| **Response Measure** | Zero raw PII fields (SSN, DOB, financial identifiers) present in LLM prompt payloads in log analysis across the validation corpus |

## Verification

- **Automated**: TBD
- **Manual**: Submit claims with PII and inspect LLM prompt logs for raw PII
