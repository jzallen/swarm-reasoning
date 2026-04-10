---
id: NFR-032
title: "Source Validator URL Coverage"
status: accepted
category: correctness
subcategory: completeness
priority: must
components: [source-validator]
adrs: [ADR-021]
tests: []
date: 2026-04-09
---

# NFR-032: Source Validator URL Coverage

## Context

The source-validator agent must extract and validate URLs from all evidence-gathering agents' observations. Incomplete coverage would allow unverified sources to influence the final verdict, undermining the system's credibility.

## Specification

| Field    | Value |
|----------|-------|
| **Scale**  | Percentage of unique source URLs across all agent observations that are extracted and validated |
| **Meter**  | Ratio of validated URLs to total unique URLs found in all agent observations for a given run |
| **Must**   | >= 90% |
| **Plan**   | >= 95% |
| **Wish**   | 100% |

## Stimulus Scenario

| Part               | Value |
|--------------------|-------|
| **Source**         | Evidence-gathering agents (coverage-left, coverage-center, coverage-right, domain-evidence, claimreview-matcher) |
| **Stimulus**       | Agents publish observations containing source URLs |
| **Environment**    | Normal operation, all evidence-gathering agents have completed |
| **Artifact**       | Source-validator agent |
| **Response**       | Source-validator extracts all unique URLs from agent observations and validates each one |
| **Response Measure** | At least 90% of unique source URLs across all agent observations are extracted and validated |

## Verification

- **Automated**: TBD
- **Manual**: After a run completes, compare the set of URLs in source-validator observations against all URLs found in evidence-gathering agent observations
