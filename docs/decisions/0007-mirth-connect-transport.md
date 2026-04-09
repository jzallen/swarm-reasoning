---
status: "superseded by [ADR-0012](0012-redis-streams-transport.md)"
date: 2026-04-08
deciders: []
---

# ADR-0007: Mirth Connect Transport

## Context and Problem Statement

HL7v2 messages must be routed between agent bundles. A transport layer is needed that understands HL7v2 framing, handles ACK/NACK semantics, and can deliver messages reliably between containers.

## Decision Drivers

- Transport must understand HL7v2 framing (MLLP)
- ACK/NACK semantics must be handled natively
- Reliable delivery between containers is required

## Decision Outcome

Chosen option: "Mirth Connect", because each agent bundle includes a Mirth Connect instance. The orchestrator's Mirth instance is the routing hub. Mirth natively understands HL7v2 MLLP framing and provides built-in ACK/NACK semantics.

### Consequences

- Good, because Mirth natively handles HL7v2 MLLP framing and ACK/NACK
- Bad, because each agent bundle requires its own Mirth instance, contributing 10 containers to the stack
- Bad, because Mirth is operationally heavy for a message routing role

## More Information

### Supersession Note

ADR-0012 replaces this decision. With HL7v2 superseded by JSON observations (ADR-0011), Mirth Connect's MLLP framing and HL7v2-native features have no role. Redis Streams replaces Mirth as the transport layer, reducing the container count from 10 Mirth instances to 1 Redis instance. Delivery guarantees are provided by Redis Streams consumer groups and acknowledgment, replacing Mirth's MLLP ACK/NACK.
