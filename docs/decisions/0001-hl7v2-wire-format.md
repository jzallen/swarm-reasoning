---
status: "superseded by [ADR-0011](0011-json-observation-schema.md)"
date: 2026-04-08
deciders: []
---

# ADR-0001: HL7v2 as Inter-Agent Wire Format

## Context and Problem Statement

A multi-agent fact-checking pipeline requires a shared wire format that agents can read, append to, and pass between one another. The format must support hierarchical data, streaming delivery, partial reads, epistemic status signaling, and provenance tracking. The two primary candidates were JSON and HL7v2 pipe-delimited messaging.

JSON is the dominant interchange format in modern API design and is well understood. However, JSON requires complete structural validity to be parseable — a missing closing bracket corrupts the entire document. LLMs generating JSON must maintain structural context across tokens, leading to higher error rates on deeply nested schemas. JSON also has no native concept of result status, acknowledgment, or message provenance.

HL7v2 is a pipe-delimited line-oriented format where each segment is self-contained and independently parseable. A single malformed segment does not corrupt adjacent segments. The format includes native fields for result status (`P` preliminary, `F` final, `C` corrected, `X` cancelled), sending application identity, message timestamp, and acknowledgment semantics. It was designed for streaming delivery over TCP. HL7v2 is natively stored in MUMPS/YottaDB globals without a serialization gap.

## Decision Drivers

- Need for line-level validity and independent parseability per segment
- Native epistemic status signaling (preliminary, final, corrected, cancelled)
- Streaming delivery compatibility
- Acknowledgment protocol support (ACK/NACK)
- Alignment with YottaDB global subscript structure

## Considered Options

1. **JSON** — Standard format with excellent tooling, universal library support, and familiarity. Structurally fragile for LLM generation. No native epistemic status. No native acknowledgment. Requires additional conventions to carry provenance.
2. **HL7v2 pipe-delimited** — Line-oriented, self-delimiting, natively streamable. OBX segments carry typed key-value observations with result status, units, reference range, and observation identity built into the segment structure. MSH segment carries message provenance. ACK/NACK semantics are part of the standard. Natively maps to YottaDB global subscript structure.
3. **TOML** — Hierarchical, locally valid at the section level, better tooling than HL7v2. No native epistemic status. Not streamable. No acknowledgment semantics. Not natively aligned with MUMPS storage.

## Decision Outcome

Chosen option: "HL7v2 pipe-delimited", because the combination of line-level validity, native result status semantics, streaming design, acknowledgment protocol, and direct alignment with YottaDB storage makes HL7v2 the most architecturally coherent choice for this system.

### Consequences

- Good, because each segment is independently parseable — a malformed segment does not corrupt adjacent segments
- Good, because native OBX.11 result status carries epistemic state without additional conventions
- Good, because MSH segment provides built-in message provenance
- Good, because ACK/NACK semantics are part of the standard
- Good, because HL7v2 natively maps to YottaDB global subscript structure with no serialization gap
- Bad, because HL7v2 introduces domain-specific complexity (escape sequences, positional field semantics, MLLP framing)
- Bad, because HL7v2 tooling ecosystem is smaller than JSON

## More Information

### Supersession Note

ADR-0011 replaces this decision. The epistemic status model, append-only semantics, and observation structure that motivated the HL7v2 choice are preserved in a typed JSON observation schema. The HL7v2 encoding added complexity without functional benefit over a well-typed JSON format with explicit status fields. The cross-domain insight (healthcare protocols solving epistemic state tracking) informed the design of the replacement schema but does not require the healthcare encoding.
