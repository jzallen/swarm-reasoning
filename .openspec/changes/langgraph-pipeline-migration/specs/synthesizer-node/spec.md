## ADDED Requirements

### Requirement: Synthesizer node produces verdict with confidence and narrative
The system SHALL implement a `synthesizer_node` async function in `pipeline/nodes/synthesizer.py` that accepts PipelineState and RunnableConfig and returns a dict with keys: verdict, confidence, narrative, verdict_observations. The node SHALL use 4 tools: resolve_observations, compute_confidence, map_verdict, generate_narrative. This is the only node that uses genuine LLM reasoning for verdict decisions.

#### Scenario: Verdict with high confidence
- **WHEN** synthesizer_node receives PipelineState with strong evidence agreement and high convergence
- **THEN** verdict is one of the standard ratings (TRUE, MOSTLY_TRUE, HALF_TRUE, MOSTLY_FALSE, FALSE, PANTS_ON_FIRE), confidence is above 0.8, and narrative explains the reasoning

#### Scenario: Verdict with low confidence due to conflicting evidence
- **WHEN** evidence sources disagree and convergence_score is below 0.3
- **THEN** confidence is below 0.5 and narrative explicitly notes the conflicting evidence

### Requirement: Synthesizer handles not-check-worthy bypass
The system SHALL produce a NOT_CHECK_WORTHY verdict when the intake node sets is_check_worthy to False. In this case, the synthesizer SHALL skip observation resolution and produce a verdict directly with confidence 1.0.

#### Scenario: Not check-worthy claim bypass
- **WHEN** synthesizer_node receives PipelineState with is_check_worthy=False
- **THEN** verdict is NOT_CHECK_WORTHY, confidence is 1.0, and narrative explains why the claim was not check-worthy

### Requirement: Synthesizer reads all upstream data from PipelineState
The system SHALL read all upstream phase outputs from PipelineState to synthesize the final verdict. The node SHALL NOT read from Redis Streams.

#### Scenario: Full pipeline data available
- **WHEN** synthesizer_node executes after all upstream nodes complete
- **THEN** it has access to intake, evidence, coverage, and validation data through PipelineState
