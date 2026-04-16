# Capability Spec: entity-extraction (delta)

## MODIFIED Requirements

### Requirement: LLM sub-call pattern

The `extract_entities` tool switches from raw `AsyncAnthropic` to `ChatAnthropic` + `RunnableConfig` via closure.

#### Scenario: Config propagation
- **WHEN** `extract_entities` is invoked by the agent
- **THEN** the tool receives `config: RunnableConfig` as a parameter
- **AND** forwards it to `model.ainvoke(messages, config)`

### Requirement: System prompt cleanup

Remove `"Do not infer or hallucinate."` from the entity extraction system prompt. The instruction is not actionable by the model. Temperature=0 provides the actual strictness control. The constraint `"Only extract entities explicitly stated in the claim text."` is retained.

#### Scenario: Updated prompt
- **WHEN** the system prompt is sent to the LLM
- **THEN** it contains `"Only extract entities explicitly stated in the claim text."`
- **AND** it does NOT contain the word `"hallucinate"`

### Requirement: Model constant

The model identifier `"claude-haiku-4-5"` is defined as a module-level constant `ENTITY_MODEL` in `agent.py`. The default parameter `model_id: str = "claude-haiku-4-5"` in `extract_entities_llm()` is removed — the model comes via closure.

### Requirement: Progress via get_stream_writer

The tool uses `get_stream_writer()` to emit progress events.

#### Scenario: Progress emission
- **WHEN** entity extraction completes
- **THEN** the tool emits `{"type": "progress", "message": "Extracted {n} entities"}`
