---
id: FR-orchestration-rules
title: "Orchestration Rules"
status: accepted
category: functional
priority: must
components: [orchestrator, temporal-server, agent-workers]
date: 2026-04-13
---

# Orchestration Rules

Functional requirements governing Temporal workflow dispatch rules, completion gates, push/pull interaction patterns, and orchestrator recovery behaviour.

---

## FR-019: No Subagent-to-Subagent Dispatch

**Description:** No agent may directly dispatch a Temporal activity to another agent. All inter-agent data requests must route through the orchestrator workflow, which fetches the data on the requesting agent's behalf.

**Acceptance Criteria:**

- When an agent requires data from another agent, it signals the orchestrator workflow to fetch the data
- The orchestrator fetches from the target agent on the requester's behalf
- No direct Temporal activity dispatch exists between any two agents

**Source:** `docs/features/agent-coordination.feature` — Scenario: "No subagent-to-subagent Temporal activity dispatch is permitted"

---

## FR-020: Orchestrator Manages All Agent Task Queues

**Description:** The orchestrator workflow is the sole dispatcher for all agent Temporal activities. The Temporal worker registry must contain exactly 11 agent task queues, one per registered agent.

**Acceptance Criteria:**

- The Temporal worker registry contains exactly 11 agent task queues
- Each entry corresponds to a registered agent
- No agent dispatches a Temporal activity to another agent

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Orchestrator workflow manages all agent task queues"

---

## FR-021: Entity Extraction Triggers Phase 2 Fan-out

**Description:** When the orchestrator receives the entity-extractor's STOP message, it must dispatch all five Phase 2a agents concurrently (claimreview-matcher, coverage-left, coverage-center, coverage-right, domain-evidence), followed by source-validator in Phase 2b after Phase 2a completes.

**Acceptance Criteria:**

- The orchestrator dispatches claimreview-matcher, coverage-left, coverage-center, coverage-right, and domain-evidence via Temporal
- All five Phase 2a dispatches occur within 500ms of one another
- After Phase 2a completes, the orchestrator dispatches source-validator in Phase 2b

**Source:** `docs/features/claim-ingestion.feature` — Scenario: "Completion of entity extraction triggers Phase 2 fan-out"

---

## FR-022: Completion on STOP Receipt, Not Activity Return

**Description:** The orchestrator must mark an agent as complete only when it receives the agent's STOP message via XREADGROUP from the Redis Stream — not when the Temporal activity dispatch returns `task_accepted`.

**Acceptance Criteria:**

- When a Temporal activity dispatch returns `task_accepted`, the completion register does NOT mark the agent complete
- When the orchestrator receives a STOP message from the agent via XREADGROUP, the completion register marks the agent complete

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Orchestrator marks agent complete on STOP receipt, not on Temporal activity return"

---

## FR-023: Blindspot Detector Gate

**Description:** The orchestrator must not dispatch the blindspot-detector until all three coverage agents (coverage-left, coverage-center, coverage-right) have published STOP messages.

**Acceptance Criteria:**

- Given coverage-left and coverage-center are complete but coverage-right has not yet published a STOP message, the orchestrator does NOT dispatch blindspot-detector

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Blindspot detector is not dispatched until coverage agents are complete"

---

## FR-024: Synthesizer Gate

**Description:** The orchestrator must not dispatch the synthesizer until all 10 preceding agents have published STOP messages. Once the final agent completes, the synthesizer must be dispatched promptly.

**Acceptance Criteria:**

- Given 10 of 11 preceding agents have published STOP messages, the orchestrator does NOT dispatch the synthesizer
- When the eleventh agent publishes its STOP message, the orchestrator dispatches the synthesizer within 5 seconds

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Synthesizer is not dispatched until all preceding agents are complete"

---

## FR-025: Agent get_observations Activity

**Description:** Each agent Temporal worker must expose a `get_observations` activity that returns observations scoped to the specified run, including code, value, units, status, and agent fields.

**Acceptance Criteria:**

- The orchestrator can invoke `get_observations` on any agent Temporal worker
- The response contains observations scoped to the specified `run_id`
- The response includes `code`, `value`, `units`, `status`, and `agent` per observation

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Each agent worker exposes get_observations activity"

---

## FR-026: Agent get_terminal_status Activity

**Description:** Each agent Temporal worker must expose a `get_terminal_status` activity that returns whether the agent has completed processing for a given run.

**Acceptance Criteria:**

- When all parallel agents have published STOP messages with F-status for a run, invoking `get_terminal_status` on each returns `true`

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Each agent worker exposes get_terminal_status activity"

---

## FR-027: Pull Pattern — Blindspot Detector Data Request

**Description:** The blindspot detector requests COVERAGE_* observations from all three coverage agents via the orchestrator. The orchestrator reads from each coverage agent's Redis Stream and returns consolidated observations in a single Temporal activity result.

**Acceptance Criteria:**

- The orchestrator reads COVERAGE_* observations from coverage-left, coverage-center, and coverage-right Redis Streams
- The orchestrator returns consolidated observations to blindspot-detector in a single Temporal activity result

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Blindspot detector requests data via orchestrator"

---

## FR-028: Pull Pattern — Synthesizer Full Observation Log

**Description:** When dispatching the synthesizer, the orchestrator must provide the full consolidated observation log from all 11 agents, filtered to include only F-status and C-status observations. P-status observations must be excluded.

**Acceptance Criteria:**

- The Temporal activity dispatch payload includes observations from all 11 agents
- The payload contains only F-status and C-status observations
- No P-status observations are included in the synthesizer payload

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Synthesizer receives full consolidated observation log via Temporal"

---

## FR-029: Unacknowledged Entry Recovery

**Description:** After a crash, the orchestrator must reclaim unacknowledged Redis Stream entries via XCLAIM and process them without duplication.

**Acceptance Criteria:**

- After restart, unacknowledged entries are visible via XPENDING
- The orchestrator reclaims them via XCLAIM
- Reclaimed entries are processed without duplication

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Orchestrator reclaims unacknowledged stream entries after recovery"

---

## FR-030: Completion State Reconstruction After Restart

**Description:** After a restart, the orchestrator must reconstruct its completion register by scanning Redis Streams for STOP messages. Already-complete agents must not be re-dispatched.

**Acceptance Criteria:**

- The orchestrator scans Redis Streams for STOP messages in the active run
- The completion register reflects all agents that have already published STOP messages
- The orchestrator resumes monitoring for the remaining agents
- No duplicate Temporal activity dispatch is issued to already-complete agents

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Orchestrator reconstructs completion state after restart"
