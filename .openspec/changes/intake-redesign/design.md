## Context

The intake agent is Phase 1 of every fact-checking run. It currently accepts raw claim text, validates it structurally, classifies its domain, normalizes it, scores check-worthiness, and extracts entities. This redesign replaces the free-text input with URL-based content extraction and user-driven claim selection.

The agent runs as a Temporal activity worker within the shared agent-service container (ADR-0016). Tools are invoked by the LLM via `create_agent` (LangGraph prebuilt). The pipeline node wrapper in `pipeline/nodes/intake.py` handles PipelineState translation and observation publishing.

Key constraints:
- ADR-004: Tool layer constructs observations — LLM never generates raw observation JSON
- ADR-012: Agents are transport-agnostic; use `get_stream_writer()` internally, Redis at boundary
- ADR-016: Agent runs as Temporal activity, no per-agent container

## Goals / Non-Goals

**Goals:**
- Accept a URL from the user instead of raw claim text
- Validate URL reachability and extract readable article content
- Decompose article content into up to 5 core factual claims
- Return claims to the user for selection (two-phase interaction)
- After selection, classify domain and extract entities on the chosen claim
- Standardize all LLM sub-calls to use `ChatAnthropic` + `RunnableConfig` via closure
- Replace deprecated `create_react_agent` with `create_agent`
- Use `get_stream_writer()` for progress emission from tools
- Remove normalizer and scorer tools

**Non-Goals:**
- Full article summarization or sentiment analysis
- Multi-claim verification in a single run (user selects one)
- Paywall bypass or JavaScript-rendered content extraction (future enhancement)
- Changes to downstream agents (evidence, coverage, validation, synthesizer)
- Frontend UI changes (separate change — this defines the contract)

## Decisions

### 1. Two-phase interaction via pipeline state

The intake agent runs in two phases within a single Temporal activity:

**Phase A** (URL → claims): User submits URL → `fetch_content` validates and extracts text → `decompose_claims` produces up to 5 claims → pipeline returns claims to the user via SSE.

**Phase B** (selection → analysis): User selects a claim → `classify_domain` categorizes it → `extract_entities` extracts named entities → pipeline publishes final observations and STOP.

The pipeline node handles the phase boundary. Phase A writes partial state (extracted claims) and signals the frontend. Phase B resumes when the user's selection arrives via the backend API.

**Alternative considered:** Two separate Temporal activities. Rejected — splitting creates orchestration complexity for what is logically one intake step. The pipeline node can manage the pause internally.

### 2. LLM sub-call pattern: ChatAnthropic via closure

All tools that make LLM sub-calls receive their `ChatAnthropic` model instance via closure from the agent builder function. Tools accept `config: RunnableConfig` as a parameter and forward it to `.ainvoke()`.

```python
def build_intake_agent(model=None):
    decompose_model = ChatAnthropic(model=DECOMPOSE_MODEL, ...)
    classify_model = ChatAnthropic(model=CLASSIFY_MODEL, ...)
    entity_model = ChatAnthropic(model=ENTITY_MODEL, ...)

    @tool
    async def decompose_claims(article_text: str, config: RunnableConfig) -> dict:
        response = await decompose_model.ainvoke([...], config)
        ...

    return create_agent(model=model, tools=[fetch_content, decompose_claims, ...])
```

This ensures LangSmith tracing, callback propagation, and streaming work across the full call tree. No tool imports `AsyncAnthropic` or `anthropic` directly.

### 3. Model selection per tool

Each tool uses the most appropriate model for its task:

| Tool | Model | Rationale |
|------|-------|-----------|
| Agent orchestrator | `claude-sonnet-4-6` | Tool selection + reasoning |
| `decompose_claims` | `claude-sonnet-4-6` | Complex reasoning: identifying factual claims in article text |
| `classify_domain` | `claude-sonnet-4-6` | Simple classification, but consistency matters |
| `extract_entities` | `claude-haiku-4-5` | Structured extraction — fast, cheap, sufficient |

Models are defined as named constants at the module level:

```python
AGENT_MODEL = "claude-sonnet-4-6"
DECOMPOSE_MODEL = "claude-sonnet-4-6"
CLASSIFY_MODEL = "claude-sonnet-4-6"
ENTITY_MODEL = "claude-haiku-4-5"
```

### 4. Content extraction via trafilatura

`fetch_content` uses the `trafilatura` library for article text extraction. Trafilatura handles boilerplate removal, encoding detection, and produces clean text from HTML. It's a well-maintained Python library specifically designed for web content extraction.

Fallback chain: trafilatura → BeautifulSoup text extraction → raw response text.

### 5. Progress emission via get_stream_writer()

Tools use LangGraph's `get_stream_writer()` to emit progress events. The pipeline node subscribes to `stream_mode="custom"` and translates these into Redis `progress:{runId}` entries.

```python
@tool
async def fetch_content(url: str) -> dict:
    writer = get_stream_writer()
    writer({"type": "progress", "message": "Fetching article content..."})
    ...
```

This keeps tools transport-agnostic per ADR-012.

### 6. Package structure

```
agents/intake/
  __init__.py              — re-exports build_intake_agent, AGENT_NAME, models
  agent.py                 — build_intake_agent(), create_agent config, model constants
  models.py                — IntakeInput, IntakeOutput (updated for URL-based flow)
  tools/
    __init__.py
    fetch_content.py       — URL validation, HTTP fetch, text extraction (trafilatura)
    decompose_claims.py    — LLM-powered claim decomposition from article text
    domain_classification.py — domain classification (renamed from domain_cls.py)
    entity_extractor.py    — NER extraction (prompt + model constant fixes)
    claim_intake.py        — KEPT: validate_source_url, normalize_date utilities only
```

Deleted: `normalizer.py`, `scorer.py`

### 7. Claim decomposition output format

`decompose_claims` returns a structured list of claims with metadata:

```python
class ExtractedClaim(BaseModel):
    index: int              # 1-5
    claim_text: str         # the factual claim
    source_quote: str       # exact quote from article supporting the claim
    category: str           # preliminary domain hint (HEALTHCARE, ECONOMICS, etc.)

class DecomposeResult(BaseModel):
    claims: list[ExtractedClaim]  # up to 5
    article_title: str
    article_date: str | None      # extracted publication date if found
```

## Risks / Trade-offs

- **[Content extraction quality]** — Trafilatura handles most news articles well but may fail on paywalled, JS-rendered, or non-standard layouts. Acceptable for MVP — paywall bypass is a non-goal.
- **[Two-phase latency]** — The user waits for fetch + decompose before seeing claims, then waits again after selection. Mitigated by streaming progress events.
- **[Claim quality depends on article quality]** — Short or poorly written articles may produce fewer than 5 claims. The tool should return however many it finds (minimum 1) and indicate if the source was limited.
- **[Frontend contract change]** — The intake response shape changes from a simple accepted/rejected to a claim selection prompt. This requires frontend coordination but is a separate change.
