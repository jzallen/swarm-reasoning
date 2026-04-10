# Non-Functional Requirements

**Framework:** ISO/IEC 25010 · Planguage · SEI Quality Attribute Scenarios

## Performance

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [NFR-001](NFR-001-end-to-end-run-latency.md) | End-to-End Run Latency | Must | Accepted |
| [NFR-002](NFR-002-parallel-fanout-latency.md) | Parallel Fan-out Phase Latency | Must | Accepted |
| [NFR-003](NFR-003-temporal-activity-dispatch-latency.md) | Temporal Activity Dispatch Latency | Must | Accepted |
| [NFR-004](NFR-004-observation-publish-throughput.md) | Observation Publish Throughput | Must | Accepted |
| [NFR-028](NFR-028-sse-progress-latency.md) | SSE Progress Event Latency | Must | Accepted |
| [NFR-030](NFR-030-static-html-render-time.md) | Static HTML Verdict Render Time | Must | Accepted |

## Reliability

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [NFR-005](NFR-005-agent-idempotency.md) | Agent Idempotency | Must | Accepted |
| [NFR-006](NFR-006-redis-delivery-retry.md) | Redis Streams Delivery Retry Behaviour | Must | Accepted |
| [NFR-007](NFR-007-orchestrator-restart-recovery.md) | Orchestrator Restart Recovery | Must | Accepted |
| [NFR-008](NFR-008-redis-write-isolation.md) | Redis Streams Write Isolation for Concurrent Observations | Must | Accepted |
| [NFR-009](NFR-009-append-only-log-integrity.md) | Append-Only Log Integrity | Must | Accepted |

## Security

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [NFR-010](NFR-010-agent-service-internal-network-only.md) | Agent Service Internal-Network-Only | Must | Accepted |
| [NFR-011](NFR-011-pii-sanitization.md) | PII Sanitization Before LLM Calls | Must | Accepted |
| [NFR-012](NFR-012-external-api-validation.md) | External API Responses Are Validated Before Observation Write | Must | Accepted |
| [NFR-013](NFR-013-observation-stream-confinement.md) | Observation Streams Are Confined to the Internal Network | Must | Accepted |
| [NFR-031](NFR-031-cloudflare-rate-limiting.md) | Cloudflare Rate Limiting | Must | Accepted |

## Maintainability

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [NFR-014](NFR-014-new-agent-modularity.md) | New Agent Can Be Added Without Modifying Existing Agents | Must | Accepted |
| [NFR-015](NFR-015-new-observation-code-no-migration.md) | New Observation Code Can Be Added Without Schema Migration | Must | Accepted |
| [NFR-016](NFR-016-transport-backend-swappable.md) | Transport Backend Is Swappable via Configuration | Must | Accepted |
| [NFR-029](NFR-029-session-ttl-cleanup.md) | Session TTL and Cleanup | Must | Accepted |

## Portability

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [NFR-017](NFR-017-single-command-local-stack.md) | Full Local Stack Runs via a Single Docker Compose Command | Must | Accepted |
| [NFR-018](NFR-018-redis-cross-platform.md) | Redis Runs in Docker on macOS and Linux | Must | Accepted |

## Correctness

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [NFR-019](NFR-019-swarm-verdict-accuracy.md) | Swarm Verdict Accuracy on PolitiFact Corpus | Must | Accepted |
| [NFR-020](NFR-020-swarm-outperforms-single-agent.md) | Swarm Outperforms Single-Agent on Non-Indexed Claims | Must | Accepted |
| [NFR-021](NFR-021-synthesis-signal-count-accuracy.md) | SYNTHESIS_SIGNAL_COUNT Accurately Reflects Evidence Breadth | Must | Accepted |
| [NFR-032](NFR-032-source-validator-coverage.md) | Source Validator URL Coverage | Must | Accepted |

## Auditability

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [NFR-022](NFR-022-traceable-audit-log.md) | Every Published Verdict Has a Traceable Audit Log | Must | Accepted |
| [NFR-023](NFR-023-correction-history-preserved.md) | Correction History Is Preserved in the Audit Log | Must | Accepted |

## Observability

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| [NFR-024](NFR-024-run-status-queryable.md) | Run Status Is Queryable at Any Point During Processing | Must | Accepted |
| [NFR-025](NFR-025-agent-heartbeat-monitoring.md) | Agent Heartbeat Is Monitored by Orchestrator | Must | Accepted |
| [NFR-026](NFR-026-observation-log-queryable.md) | Observation Log Is Queryable for Post-Run Analysis | Must | Accepted |
| [NFR-027](NFR-027-stream-delivery-error-logging.md) | Stream Delivery Errors Surface in the Run Error Log | Must | Accepted |
