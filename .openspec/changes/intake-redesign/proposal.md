## Why

The current intake agent accepts free-form claim text from users, which makes deterministic fact-checking harder. Users must already know what factual claim they want verified and phrase it correctly. The normalizer tool attempts to clean messy input via regex (hedge removal, pronoun resolution, lowercasing) but is fragile, destroys proper nouns, and adds no measurable value. The check-worthiness scorer makes two LLM calls to gate claims that the user themselves selected — redundant when the system can verify that real source content exists.

Additionally, the intake agent's tools use three inconsistent patterns for LLM sub-calls (raw `AsyncAnthropic` with `call_claude`, a separate `_call_claude`, and inline `client.messages.create`), none of which propagate `RunnableConfig` for LangSmith tracing. The `create_react_agent` constructor is deprecated in current LangGraph — `create_agent` is the replacement.

## What Changes

- **Redesign intake flow**: user submits a URL instead of raw claim text. The agent fetches and validates the content, decomposes it into up to 5 core factual claims, and returns them to the user for selection. After selection, domain classification and entity extraction run on the chosen claim.
- **Delete normalizer** (`normalizer.py`): lowercasing destroys proper nouns before entity extraction, hedge regex is fragile, pronoun resolution receives no entity input at call time. The LLM handles normalization implicitly.
- **Delete scorer** (`scorer.py`): two-pass self-consistency LLM protocol is unnecessary when the source URL's existence validates the content and the user explicitly selects which claim to verify.
- **Rename `domain_cls.py`** → `domain_classification.py` for readability.
- **Standardize LLM sub-call pattern**: all tools use `ChatAnthropic` + `RunnableConfig` via closure from the agent builder function. No tool directly imports or instantiates `AsyncAnthropic`.
- **Replace `create_react_agent`** with `create_agent` (LangGraph deprecation).
- **Use `get_stream_writer()`** for intra-pipeline progress emission. Redis Streams publishing moves to the pipeline node boundary.
- **Remove "do not hallucinate"** from entity extraction prompt — not actionable by the model; temperature=0 provides the actual control.
- **Extract model constants**: replace magic strings (`"claude-haiku-4-5"`, `"claude-sonnet-4-6"`) with named constants at the agent module level.

## Capabilities

### New Capabilities

- `fetch-content`: LangChain tool that validates a URL is reachable, fetches the page content, and extracts readable article text. Returns the extracted text or a structured error if the URL is invalid, unreachable, or unparseable.
- `decompose-claims`: LLM-powered tool that analyzes article text and extracts up to 5 core factual claims suitable for fact-checking. Returns a ranked list for user selection.

### Modified Capabilities

- `domain-classification`: renamed file, switched from raw `AsyncAnthropic` to `ChatAnthropic` + `RunnableConfig` via closure. Functional behavior unchanged.
- `entity-extraction`: removed "do not hallucinate" from system prompt, model ID moved to named constant, switched to `ChatAnthropic` + `RunnableConfig` via closure.

### Removed Capabilities

- `normalize-claim`: deleted — regex-based normalization is fragile and destructive.
- `score-check-worthiness`: deleted — URL-based intake with user claim selection replaces the check-worthiness gate.
- `validate-claim`: replaced by `fetch-content` — URL validation replaces text-length validation.

## Impact

- **Modified module**: `services/agent-service/src/swarm_reasoning/agents/intake/` — tools rewritten, agent builder updated
- **Deleted files**: `tools/normalizer.py`, `tools/scorer.py`
- **Renamed files**: `tools/domain_cls.py` → `tools/domain_classification.py`
- **New files**: `tools/fetch_content.py`, `tools/decompose_claims.py`
- **Modified files**: `agent.py` (new tool list, `create_agent`, closure pattern), `tools/entity_extractor.py` (prompt fix, closure pattern)
- **Pipeline node**: `pipeline/nodes/intake.py` must be updated for new tool outputs and the two-phase interaction (fetch → user selects → classify + extract)
- **Frontend impact**: the chat UI must handle the claim selection response (display 5 claims, accept user choice)
- **Depends on**: `langchain_anthropic.ChatAnthropic`, `langgraph.prebuilt.create_agent`, `langgraph.config.get_stream_writer`
