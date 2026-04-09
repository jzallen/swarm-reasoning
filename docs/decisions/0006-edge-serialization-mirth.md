---
status: "superseded by [ADR-0011](0011-json-observation-schema.md)"
date: 2026-04-08
deciders: []
---

# ADR-0006: Edge Serialization via Mirth

## Context and Problem Statement

Downstream consumers — dashboards, REST API clients, analyst tools — expect JSON. They should not need to understand HL7v2 segment structure. A serialization adapter was required to transform finalized HL7v2 messages into JSON at the system boundary.

## Decision Drivers

- Downstream consumers expect JSON and should not need to understand HL7v2
- Transformation must happen at the system boundary
- Adapter must handle finalized messages reliably

## Considered Options

1. **Custom serialization service** — A bespoke service to transform HL7v2 to JSON. Requires building and maintaining custom parsing logic.
2. **Mirth Connect adapter** — A dedicated Mirth channel subscribes to finalized messages and maps OBX rows to JSON. Leverages Mirth's native HL7v2 parsing capabilities.

## Decision Outcome

Chosen option: "Mirth Connect adapter", because Mirth Connect serves as the edge serialization adapter. A dedicated Mirth channel subscribes to finalized messages and maps OBX rows to JSON, leveraging Mirth's native HL7v2 parsing capabilities.

### Consequences

- Good, because Mirth natively understands HL7v2 segment structure, simplifying the transformation
- Bad, because it introduces an additional Mirth channel dependency for the consumer-facing API
- Bad, because the edge serialization layer exists only because the internal format (HL7v2) differs from the external format (JSON)

## More Information

### Supersession Note

ADR-0011 replaces this decision. With JSON as the native observation format (ADR-0011), no edge serialization adapter is needed. The observation schema is directly consumable by dashboards, API clients, and analyst tools. The edge-serializer agent role is eliminated.
