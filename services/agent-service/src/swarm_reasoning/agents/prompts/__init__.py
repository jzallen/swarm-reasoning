"""Shared prompt constants for LangChain agents (ADR-004).

TOOL_USAGE_SUFFIX is appended to all agent system prompts to instruct
the LLM on how to publish observations and progress via the tool layer.
"""

TOOL_USAGE_SUFFIX = """\

## Publishing Observations

You MUST use the `publish_observation` tool for every finding. Never produce \
raw observation JSON yourself — the tool layer handles schema validation, \
sequencing, and timestamps.

### Tool: publish_observation

Parameters:
- **code** (required): Observation code from the OBX registry (e.g. \
CLAIM_TEXT, CHECK_WORTHY_SCORE, VERDICT). Only use codes assigned to your agent.
- **value** (required): The observation value as a string. Format depends on \
the value type for that code:
  - ST (short string): plain text, max 200 characters (e.g. "Reuters")
  - NM (numeric): decimal string parseable as float (e.g. "0.84")
  - CWE (coded value): CODE^Display^System format (e.g. "TRUE^True^POLITIFACT")
  - TX (long text): plain text, must exceed 200 characters
- **status** (default "F"): Epistemic status of the observation:
  - P = Preliminary — initial finding, not yet corroborated
  - F = Final — you consider this finding settled
  - C = Corrected — supersedes an earlier observation of the same code
  - X = Cancelled — finding retracted or claim not check-worthy
- **method** (optional): Name of the method or tool that produced this finding.
- **note** (optional): Free-text annotation, max 512 characters.

### Tool: publish_progress

Use `publish_progress` to send human-readable status updates displayed to the \
user in real time (e.g. "Analyzing coverage from left-leaning sources..."). \
Call this before major processing steps so users can follow your progress.

### Rules

1. Publish at least one F or X observation for each of your registered codes \
before completing.
2. You may publish P (preliminary) observations freely during reasoning.
3. To correct a prior finding, publish a new observation with the same code \
and status C — the original is never modified (append-only log).
4. Always provide the `method` parameter when the observation comes from a \
specific analysis step.
"""
