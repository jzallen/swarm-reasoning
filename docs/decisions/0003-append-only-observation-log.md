---
status: accepted
date: 2026-04-08
deciders: []
---

# ADR-0003: Append-Only Observation Log

## Context and Problem Statement

As agents contribute findings to a fact-checking run, the collective reasoning state grows. A design choice exists between mutable shared state (agents overwrite or update a central record) and an append-only log (agents add new observation entries; earlier entries are never modified).

Mutable shared state simplifies the final read — there is always one current value per field. However, it destroys the history of how the system's confidence evolved, makes concurrent writes conflict-prone, and prevents attribution of which agent asserted what at which point.

An append-only log preserves the full reasoning trajectory. Corrections are expressed as new observation entries with `C` (corrected) status referencing the original observation, not as overwrites. The synthesizer reads the full log and resolves the current authoritative value by status and sequence.

## Decision Drivers

- Full reasoning trajectory must be preserved for interpretability
- Audit trail: which agent introduced a finding, which agent corrected it, how confidence evolved
- Concurrent writes must not conflict
- Corrections must be expressible without destroying history

## Considered Options

1. **Mutable shared state** — Agents overwrite or update a central record. Simplifies the final read but destroys history, makes concurrent writes conflict-prone, and prevents attribution.
2. **Append-only log** — Agents add new observation entries; earlier entries are never modified. Corrections are expressed as new entries with `C` (corrected) status.

## Decision Outcome

Chosen option: "Append-only log", because the reasoning log is the primary source of the system's interpretability claim. The audit trail — which agent introduced a finding, which agent corrected it, how confidence evolved from `P` to `F` — is only possible if history is preserved.

### Consequences

- Good, because the full reasoning trajectory is preserved for audit and interpretability
- Good, because concurrent writes never conflict — all writes are appends
- Good, because corrections are traceable via `C` status entries referencing the original
- Bad, because the synthesizer must implement log resolution logic: given multiple observation entries for the same code, determine the authoritative current value by selecting the most recent `F` or `C` status entry
- Bad, because Redis Stream storage grows monotonically per run; `MAXLEN` or `MINID` trimming policy is required for long-running deployments but is out of scope for the prototype
- Neutral, because query patterns must account for log structure — "What is the current confidence score?" requires a scan of all CONFIDENCE_SCORE entries and selection of the latest authoritative one

## More Information

### Update Note

This decision survives the transport change from HL7v2/YottaDB to JSON/Redis Streams. Redis Streams are append-only by nature — entries are immutable once written. The `XADD` command appends; there is no update-in-place. The log resolution logic in the synthesizer is unchanged: given multiple observations for the same code, select the most recent `F` or `C` status entry as authoritative.
