## Why

The swarm-reasoning system orchestrates 11 agents across three phases to produce a verdict. Temporal.io replaces MCP as the control plane (ADR-016), providing durable execution, automatic retry, activity timeouts, and workflow visibility. Without Temporal integration, there is no mechanism to dispatch agents, handle failures, or coordinate the three-phase execution DAG. Both the NestJS backend (workflow client) and the Python agent service (activity workers) depend on this slice.

## What Changes

- Define `ClaimVerificationWorkflow` as a Temporal workflow implementing the three-phase DAG: sequential ingestion, parallel fan-out, sequential synthesis
- Define activity interfaces for all 11 agents with typed input/output contracts
- Configure Temporal worker registration in the Python agent service (one worker per agent type)
- Implement retry policies: 3 retries with exponential backoff for transient LLM/API failures
- Set activity timeouts: 30s for Phase 1 agents, 45s for Phase 2, 60s for Phase 3
- Implement workflow signals for NestJS backend completion notification
- Design task queue topology: one queue per agent type for independent scaling

## Capabilities

### New Capabilities
- `workflow-definition`: ClaimVerificationWorkflow with three-phase DAG, run status updates, cancellation support, and completion signaling
- `activity-contracts`: Typed activity interfaces for all 11 agents with input (runId, claim data, phase context) and output (terminal status, observation count)
- `worker-configuration`: Temporal worker setup in the Python agent service, task queue registration, graceful shutdown

### Modified Capabilities

## Impact

- **Python agent service**: Temporal SDK dependency, worker registration, activity implementations wrapping LangChain agents
- **NestJS backend**: Temporal client adapter starts workflows and receives completion signals
- **Infrastructure**: Temporal server + UI added to docker-compose (temporal, temporal-ui, temporal-db services)
- **Dependencies**: temporalio (Python), @temporalio/client (TypeScript/NestJS)
