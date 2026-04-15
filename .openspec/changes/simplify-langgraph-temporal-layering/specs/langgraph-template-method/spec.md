## ADDED Requirements

### Requirement: Template method for input message construction
`LangGraphBase` SHALL define a `_build_input_message(self, context: ClaimContext) -> str` method that constructs the human message for the LangGraph agent. Subclasses SHALL override this method to customize message content.

#### Scenario: Default message construction
- **WHEN** a LangGraphBase agent with no `_build_input_message` override executes
- **THEN** the default implementation SHALL format the claim context using the existing `_format_claim_input()` helper

#### Scenario: CoverageHandler message customization
- **WHEN** a CoverageHandler agent executes
- **THEN** its `_build_input_message()` override SHALL append source IDs and source JSON to the base message

#### Scenario: SynthesizerHandler message customization
- **WHEN** the synthesizer agent executes
- **THEN** its `_build_input_message()` override SHALL append synthesis-specific context to the base message

### Requirement: Single canonical _execute() in LangGraphBase
The `create_react_agent` construction, `ChatAnthropic` instantiation, deprecation warning suppression, `graph.ainvoke()` call, and `seq_counter` sync SHALL exist only in `LangGraphBase._execute()`. No subclass SHALL duplicate this block.

#### Scenario: No duplicate graph construction
- **WHEN** searching the codebase for `create_react_agent` calls in agent handler files
- **THEN** exactly one invocation SHALL exist, in `langgraph_base.py`

#### Scenario: Subclass customization via hooks only
- **WHEN** a LangGraphBase subclass needs custom behavior
- **THEN** it SHALL override `_build_input_message()`, `_tools()`, `_system_prompt()`, or `_model_id()` — not `_execute()`
