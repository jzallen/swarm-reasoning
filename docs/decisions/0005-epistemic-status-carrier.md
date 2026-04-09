---
status: accepted
date: 2026-04-08
deciders: []
---

# ADR-0005: Epistemic Status Carrier

## Context and Problem Statement

In a multi-agent pipeline where findings evolve over time, downstream agents need to know whether an upstream observation is a hypothesis, a confirmed finding, a correction of an earlier finding, or a retraction. This epistemic state must be structural — carried in the data, not inferred from prose — so that agents can act on it programmatically.

## Decision Outcome

Observation entries carry a `status` field with the following values:

| Status | Meaning in this system |
|---|---|
| `P` | Preliminary — hypothesis or initial finding, not yet corroborated |
| `F` | Final — confirmed finding, agent considers this settled |
| `C` | Corrected — supersedes an earlier observation of the same code |
| `X` | Cancelled — claim determined not check-worthy or finding retracted |

This model was informed by HL7v2's OBX.11 result status semantics, which solved the same epistemic state tracking problem in clinical observation reporting. The status values are carried as a typed field in the JSON observation schema rather than in a positional HL7v2 field.

The synthesizer treats only `F` and `C` status entries as authoritative inputs to the final verdict. `P` entries are informational. `X` entries are excluded from synthesis but retained in the log for auditability.

### Consequences

- Good, because epistemic state is structural and machine-readable, enabling programmatic handling by downstream agents
- Good, because the P/F/C/X model maps cleanly to the observation lifecycle (hypothesis, confirmation, correction, retraction)
- Bad, because agents must set status deliberately — emitting `F` status is a commitment that the finding is settled from that agent's perspective
- Neutral, because `P` status entries from parallel agents may temporarily contradict one another; this is expected and resolved by the synthesizer
- Neutral, because the orchestrator uses status as a completion signal: when all expected agents have emitted at least one `F` or `X` entry for their assigned observation codes, the run is eligible for synthesis
