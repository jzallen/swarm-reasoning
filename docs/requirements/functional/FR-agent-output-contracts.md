---
id: FR-agent-output-contracts
title: "Agent Output Contracts"
status: accepted
category: functional
priority: must
components: [ingestion-agent, claim-detector, entity-extractor, coverage-agents]
date: 2026-04-13
---

# Agent Output Contracts

Functional requirements governing the observation outputs each agent must publish. Every agent writes typed JSON observations to its Redis Stream; these requirements define what codes, statuses, and attribution rules apply.

---

## FR-001: Ingestion Agent Required Observations

**Description:** The ingestion agent must publish a complete set of F-status observations covering the claim text, source URL, source date, and domain classification before emitting a STOP message.

**Acceptance Criteria:**

- The agent stream contains an F-status observation for code `CLAIM_TEXT`
- The agent stream contains an F-status observation for code `CLAIM_SOURCE_URL`
- The agent stream contains an F-status observation for code `CLAIM_SOURCE_DATE`
- The agent stream contains an F-status observation for code `CLAIM_DOMAIN`
- The agent stream contains a STOP message with `finalStatus: "F"`

**Source:** `docs/features/claim-ingestion.feature` — Scenario: "Ingestion agent publishes required observations"

---

## FR-002: Ingestion Agent Attribution

**Description:** All observations published by the ingestion agent must carry the correct agent identity so downstream consumers and the audit log can trace each observation to its source.

**Acceptance Criteria:**

- All observations published by the ingestion agent have `agent = "ingestion-agent"`

**Source:** `docs/features/claim-ingestion.feature` — Scenario: "Ingestion agent observations are attributed correctly"

---

## FR-003: Special Character Handling in Claim Text

**Description:** The ingestion agent must store claim text verbatim, including special characters such as pipe (`|`), without mangling or escaping errors. The resulting JSON observation must remain parseable.

**Acceptance Criteria:**

- A claim text containing pipe characters is stored as-is in the observation value
- The JSON observation is parseable without errors

**Source:** `docs/features/claim-ingestion.feature` — Scenario: "Claim text containing special characters is stored correctly"

---

## FR-004: Claim Detector Normalized Output

**Description:** The claim detector must publish a normalized version of the claim text. Normalization lowercases the text and removes hedging phrases.

**Acceptance Criteria:**

- The agent stream contains an F-status observation for code `CLAIM_NORMALIZED`
- The `CLAIM_NORMALIZED` value is lowercase
- The `CLAIM_NORMALIZED` value does not contain hedging phrases like "reportedly" or "allegedly"

**Source:** `docs/features/claim-ingestion.feature` — Scenario: "Claim detector publishes normalized claim text"

---

## FR-005: Entity Extractor Per-Entity Output

**Description:** The entity extractor must publish one observation per extracted entity, using the appropriate `ENTITY_*` observation code for the entity type (person, organization, date, statistic, etc.).

**Acceptance Criteria:**

- The agent stream contains exactly one F-status observation per extracted entity
- Each observation uses the correct code: `ENTITY_PERSON`, `ENTITY_ORG`, `ENTITY_DATE`, etc.
- Entity counts match the entities present in the claim text

**Source:** `docs/features/claim-ingestion.feature` — Scenario: "Entity extractor publishes one observation per extracted entity"

---

## FR-006: Entity Extractor No-Statistic Case

**Description:** When the claim text contains no numeric quantities, the entity extractor must not emit any `ENTITY_STATISTIC` observations. This prevents false-positive statistical claims from polluting downstream analysis.

**Acceptance Criteria:**

- For claims with no numeric content, the agent stream contains zero observations for code `ENTITY_STATISTIC`

**Source:** `docs/features/claim-ingestion.feature` — Scenario: "Entity extractor emits no ENTITY_STATISTIC observations for claims without numeric content"

---

## FR-007: Coverage Agent Stream Output

**Description:** Each coverage agent (left, center, right) must publish its analysis results — including article count and framing — to its own Redis Stream, with correct agent attribution and a STOP message.

**Acceptance Criteria:**

- The agent publishes observations to stream `reasoning:{runId}:{agent-name}`
- The stream contains F-status observations for `COVERAGE_ARTICLE_COUNT`
- The stream contains F-status observations for `COVERAGE_FRAMING`
- The `agent` field on all observations equals the publishing agent's name
- The stream contains a STOP message within 30 seconds

**Source:** `docs/features/agent-coordination.feature` — Scenario: "Coverage agent completes task and publishes observations to its stream"
