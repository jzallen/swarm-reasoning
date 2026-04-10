# Business Rules — Swarm-Reasoning Fact-Checking System

> Expressed in **SBVR** (Semantics of Business Vocabulary and Business Rules) structured English.
> Modal keywords follow OMG SBVR v1.5 notation.
>
> Entity-specific invariants, value objects, state transitions, and creation rules are
> documented in individual entity files under [`entities/`](entities/).
> This file contains **cross-entity rules** — constraints that span multiple entities
> and cannot be expressed within a single entity boundary.

---

## 1  Vocabulary (Terms)

| Term | Definition |
|------|-----------|
| _claim_ | A natural-language assertion submitted for fact-checking. |
| _session_ | A bounded processing context that owns exactly one _claim_ and all artifacts produced while checking it. |
| _run_ | A single end-to-end execution of the agent pipeline within a _session_. |
| _agent_ | A specialized software component that performs one step of the fact-checking pipeline and publishes _observations_. |
| _observation_ | A typed, immutable JSON record published by an _agent_ to the _observation log_. |
| _observation code_ | A code from the _observation code registry_ that classifies the kind of information an _observation_ carries. |
| _observation code registry_ | The authoritative catalogue of all valid _observation codes_ and their owning _agents_ (see `obx-code-registry.json`). |
| _observation log_ | The append-only Redis Streams log to which all _observations_ are written. |
| _epistemic status_ | A single-character tag on an _observation_ indicating its certainty state: P (preliminary), F (final), C (corrected), X (cancelled). |
| _verdict_ | The final output of a _run_, containing a _factuality score_, rating label, and _citation list_. |
| _citation_ | A reference to a _source URL_ together with the _agent_ and _observation code_ that discovered it. |
| _citation list_ | An ordered collection of _citations_ aggregated into a _verdict_. |
| _progress event_ | A user-friendly status message published to the progress stream during agent execution. |
| _factuality score_ | A decimal number in the range 0.0 to 1.0 representing the assessed truthfulness of a _claim_. |
| _source URL_ | A web address cited as evidence by an _agent_. |
| _stream key_ | The Redis Streams key that identifies an agent's observation stream, formatted as `reasoning:{runId}:{agent}`. |
| _orchestrator_ | The central coordinator that dispatches _agents_ across three execution phases via Temporal workflows. |
| _source-validator_ | The _agent_ responsible for URL validation and source convergence scoring. |

---

## 2  Fact Types (Verbs)

1. _session_ **contains** _claim_.
2. _session_ **has** _status_.
3. _session_ **owns** _run_.
4. _run_ **produces** _verdict_.
5. _run_ **dispatches** _agent_.
6. _agent_ **publishes** _observation_.
7. _agent_ **owns** _observation code_.
8. _observation_ **has** _observation code_.
9. _observation_ **has** _epistemic status_.
10. _observation_ **is appended to** _observation log_.
11. _observation_ **is written to** _stream key_.
12. _verdict_ **includes** _factuality score_.
13. _verdict_ **includes** _citation list_.
14. _verdict_ **maps** _factuality score_ **to** rating label.
15. _citation_ **references** _source URL_.
16. _citation_ **identifies** _agent_.
17. _citation_ **identifies** _observation code_.
18. _agent_ **publishes** _progress event_.
19. _orchestrator_ **dispatches** _agent_.
20. _source-validator_ **validates** _source URL_.

---

## 3  Cross-Entity Business Rules

### 3.1  Orchestration → Agent → Observation

1. It is **obligatory** that the _orchestrator_ executes _agents_ in three phases: sequential ingestion, parallel fan-out, sequential synthesis.
2. It is **obligatory** that Phase 1 _agents_ complete before Phase 2 _agents_ are dispatched.
3. It is **obligatory** that Phase 2 _agents_ complete before Phase 3 _agents_ are dispatched.
4. It is **possible** that the _orchestrator_ retries a failed _agent_ activity according to the Temporal retry policy.

### 3.2  Agent → Observation → Verdict

1. It is **prohibited** that a _verdict_ is emitted if any Phase 2 _agent_ has not published a terminal _epistemic status_ (**F** or **X**).
2. It is **obligatory** that the synthesizer's _verdict_ reflects only _observations_ with _epistemic status_ **F** (final) or **C** (corrected).
3. It is **obligatory** that each _citation_ in the _citation list_ is derived from _observations_ published by _agents_ during the _run_.

### 3.3  Source Validation → Citation → Verdict

1. It is **obligatory** that the _source-validator_ extracts _source URLs_ from all evidence-gathering _agents_' _observations_.
2. It is **obligatory** that each _citation_ in the _verdict_ includes a validation status from the _source-validator_.
3. It is **obligatory** that the _source-validator_ publishes a SOURCE_CONVERGENCE_SCORE when multiple _agents_ cite the same underlying _source URL_.

### 3.4  Session → Verdict → Static Snapshot

1. It is **obligatory** that a _session_ transitions from active to frozen when its _verdict_ is finalized.
2. It is **obligatory** that a static HTML snapshot is rendered when a _session_ transitions to frozen.
3. It is **obligatory** that the static HTML snapshot includes both the _verdict_ view and the _progress event_ chat log.

### 3.5  Progress Events → SSE → Frontend

1. It is **obligatory** that _progress events_ published by _agents_ are relayed to the frontend via SSE.
2. It is **obligatory** that the final SSE event carries the completed _verdict_ payload.
3. It is **obligatory** that after the final verdict event, the SSE connection is closed and the _session_ is frozen.

### 3.6  Session → Cleanup

1. It is **obligatory** that an expired _session_ and all associated data (_run_, _observations_, _verdict_, _citations_, _progress events_, static snapshot) are deleted within 24 hours of expiration.
