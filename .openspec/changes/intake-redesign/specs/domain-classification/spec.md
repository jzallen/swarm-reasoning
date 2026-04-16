# Capability Spec: domain-classification (delta)

## MODIFIED Requirements

### Requirement: LLM sub-call pattern

The `classify_domain` tool switches from raw `AsyncAnthropic` + `call_claude()` to `ChatAnthropic` + `RunnableConfig` via closure.

#### Scenario: Config propagation
- **WHEN** `classify_domain` is invoked by the agent
- **THEN** the tool receives `config: RunnableConfig` as a parameter
- **AND** forwards it to `model.ainvoke(messages, config)`
- **AND** LangSmith tracing captures the sub-call

### Requirement: File rename

The tool file is renamed from `domain_cls.py` to `domain_classification.py`. All imports are updated.

### Requirement: Model constant

The model identifier `"claude-sonnet-4-6"` is defined as a module-level constant `CLASSIFY_MODEL` in `agent.py`, not hardcoded in the tool.

### Requirement: Progress via get_stream_writer

The tool uses `get_stream_writer()` to emit progress events instead of publishing directly to Redis.

#### Scenario: Progress emission
- **WHEN** classification completes
- **THEN** the tool emits `{"type": "progress", "message": "Domain classified: {domain}"}`
- **AND** the pipeline node translates this to a Redis progress entry

## REMOVED Requirements

### Requirement: call_claude function

The standalone `call_claude(client, prompt)` function in `domain_cls.py` is deleted. LLM calls go through `ChatAnthropic.ainvoke()`.

### Requirement: _get_anthropic_client factory

The `_get_anthropic_client()` function in `agent.py` is deleted. Model instances are created in `build_intake_agent()` and passed via closure.
