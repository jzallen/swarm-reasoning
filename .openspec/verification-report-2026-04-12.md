# OpenSpec Task Verification Report

**Date:** 2026-04-12
**Bead:** hq-khm
**Auditor:** polecat/jasper

## Executive Summary

All 16 openspec changes in `.openspec/changes/` were cross-referenced against the codebase. **No unchecked tasks need to be checked off** — all `[ ]` items are genuinely unimplemented. Two changes are 100% complete. The remaining 14 have gaps primarily in integration tests, Temporal `@activity.defn` wrappers (agents use `@register_handler` pattern instead), and Gherkin step definitions.

## Summary Table

| # | Change | Marked Done | Actually Done | % | Status |
|---|--------|-------------|---------------|---|--------|
| 1 | blindspot-domain-evidence | 16/21 | 16/21 | 76% | Missing: orchestrator integration, activity test, Gherkin validation |
| 2 | claim-detector | 30/34 | 30/34 | 88% | Missing: heartbeat test, integration tests, acceptance tests |
| 3 | deployment-infrastructure | 58/58 | 58/58 | **100%** | COMPLETE |
| 4 | entity-extractor | 32/34 | 32/34 | 94% | Missing: multi-run isolation test, retry test |
| 5 | frontend-chat-ui | 89/96 | 89/96 | 93% | Missing: all unit/integration tests (7), popstate handler |
| 6 | ingestion-agent | 100/103 | 100/103 | 97% | Missing: handler unit test, vocabulary coverage test, retry test |
| 7 | nestjs-backend-core | 107/115 | 107/115 | 93% | Missing: @temporalio/client dep, tsconfig aliases, tests |
| 8 | orchestrator-core | 126/147 | 126/147 | 86% | Missing: asyncpg/sqlalchemy deps, recovery path, 15 tests |
| 9 | parallel-fanout-agents | 25/35 | 25/35 | 71% | Missing: @activity.defn wrappers, LangChain integration, Phase 2 integration test |
| 10 | redis-streams-observation-schema | 17/17 | 17/17 | **100%** | COMPLETE |
| 11 | source-validator-agent | 43/44 | 43/44 | 98% | Missing: activity registration unit test |
| 12 | sse-progress-relay | 31/38 | 31/38 | 82% | Missing: stream error handling, disconnect detection, backoff |
| 13 | static-html-snapshots | ~42/50 | ~42/50 | 84% | Missing: ServeStaticModule, session-frozen event, snapshot store tests, integration tests |
| 14 | synthesizer-verdict | ~35/47 | ~35/47 | 75% | Missing: @activity.defn pattern, integration tests, Gherkin steps |
| 15 | temporal-workflow-integration | ~38/48 | ~38/48 | 79% | Missing: NestJS @temporalio/client, SSE status publishing, signal handler |
| 16 | validation-harness | ~30/38 | ~30/38 | 79% | Missing: baseline_mode in orchestrator, Makefile, CI integration |

**Overall: ~819/949 tasks complete (~86%)**

## Recurring Gap Patterns

### 1. Temporal @activity.defn vs @register_handler (Affects: 5 changes)
All Python agents use `@register_handler('agent-name')` decorator pattern instead of Temporal's `@activity.defn`. This is a consistent architectural deviation from the openspec — either the specs need updating to reflect the actual pattern, or wrapper functions need to be created.

**Affected:** blindspot-domain-evidence, parallel-fanout-agents, source-validator-agent, synthesizer-verdict, temporal-workflow-integration

### 2. Missing Integration Tests (Affects: 10 changes)
Integration tests are the largest category of incomplete tasks across nearly all changes. Unit tests are generally complete.

**Affected:** blindspot-domain-evidence, claim-detector, frontend-chat-ui, nestjs-backend-core, orchestrator-core, parallel-fanout-agents, sse-progress-relay, static-html-snapshots, synthesizer-verdict, validation-harness

### 3. Missing Gherkin Step Definitions (Affects: 3 changes)
Feature files exist but step definitions are not implemented.

**Affected:** blindspot-domain-evidence, synthesizer-verdict, validation-harness

### 4. Missing NestJS Dependencies (Affects: 2 changes)
`@temporalio/client` is not in backend package.json, blocking proper Temporal integration from the NestJS side.

**Affected:** nestjs-backend-core, temporal-workflow-integration

### 5. Missing Python Dependencies (Affects: 1 change)
`asyncpg` and `sqlalchemy[asyncio]` missing from orchestrator pyproject.toml.

**Affected:** orchestrator-core

## Changes Requiring No Action (100% Complete)

1. **deployment-infrastructure** — All Docker, ECS, CloudFormation, Cloudflare, Helm, and CI/CD configs implemented
2. **redis-streams-observation-schema** — All models, stream abstractions, Redis adapter, and tests implemented

## Conclusion

The existing task checkmarks are accurate. No `[ ]` tasks were found to be secretly complete. The codebase restructure did not invalidate any previously-checked tasks. The primary remaining work is:
1. Integration/e2e tests across most changes
2. Deciding whether to adopt `@activity.defn` or update specs to reflect `@register_handler`
3. Adding missing NestJS/Python dependencies for Temporal integration
4. Implementing Gherkin step definitions
