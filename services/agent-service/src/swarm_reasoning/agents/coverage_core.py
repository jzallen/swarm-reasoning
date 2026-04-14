"""Shared logic for coverage-left, coverage-center, coverage-right agents.

Provides NewsAPI query building, headline sentiment analysis (simplified
VADER-style lexicon scoring), and top-source selection by credibility rank.
CoverageHandler extends LangGraphBase for LLM-driven ReAct orchestration.
"""

from __future__ import annotations

import json
import logging
import re
import warnings
from pathlib import Path

import redis.asyncio as aioredis
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

from swarm_reasoning.agents._utils import STOP_WORDS
from swarm_reasoning.agents.fanout_base import ClaimContext
from swarm_reasoning.agents.langgraph_base import LangGraphBase, _format_claim_input
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

NEWSAPI_URL = "https://newsapi.org/v2/everything"

# Simplified VADER-style lexicon for headline sentiment
_POSITIVE_WORDS = frozenset(
    {
        "good",
        "great",
        "best",
        "better",
        "positive",
        "success",
        "successful",
        "gain",
        "gains",
        "rise",
        "rises",
        "rising",
        "grew",
        "grow",
        "growth",
        "improve",
        "improved",
        "improvement",
        "strong",
        "strength",
        "boost",
        "boosted",
        "win",
        "wins",
        "winning",
        "won",
        "progress",
        "achievement",
        "benefit",
        "benefits",
        "effective",
        "approve",
        "approved",
        "support",
        "supports",
        "supported",
        "helpful",
        "increase",
        "increased",
        "up",
        "record",
        "high",
        "correct",
        "true",
        "confirmed",
        "proven",
        "accurate",
        "safe",
        "recover",
        "recovery",
        "surge",
        "surging",
        "soar",
        "soaring",
    }
)

_NEGATIVE_WORDS = frozenset(
    {
        "bad",
        "worst",
        "worse",
        "negative",
        "fail",
        "failed",
        "failure",
        "loss",
        "losses",
        "fall",
        "falls",
        "falling",
        "fell",
        "decline",
        "declined",
        "weak",
        "weakness",
        "drop",
        "dropped",
        "lose",
        "losing",
        "lost",
        "crisis",
        "problem",
        "problems",
        "damage",
        "damaged",
        "threat",
        "threatens",
        "risk",
        "risks",
        "dangerous",
        "danger",
        "wrong",
        "false",
        "lie",
        "lies",
        "misleading",
        "debunked",
        "denied",
        "deny",
        "reject",
        "rejected",
        "crash",
        "crashed",
        "collapse",
        "collapsed",
        "cut",
        "cuts",
        "killed",
        "dead",
        "death",
        "harm",
        "harmful",
        "concern",
        "concerns",
        "warning",
        "warned",
        "fears",
        "fear",
        "down",
        "low",
        "record-low",
    }
)

_NEGATION_WORDS = frozenset(
    {
        "not",
        "no",
        "never",
        "neither",
        "nor",
        "hardly",
        "barely",
        "doesn't",
        "don't",
        "didn't",
        "won't",
        "wouldn't",
        "couldn't",
        "shouldn't",
    }
)

_WORD_RE = re.compile(r"[a-z'-]+")


def build_search_query(context: ClaimContext) -> str:
    """Build a NewsAPI search query from normalized claim, removing stop words.

    Truncates to 100 characters at word boundary.
    """
    words = context.normalized_claim.lower().split()
    filtered = [w for w in words if w not in STOP_WORDS]
    query = " ".join(filtered)

    if len(query) <= 100:
        return query

    # Truncate at word boundary
    truncated = query[:100]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space]
    return truncated


def compute_compound_sentiment(headlines: list[str]) -> float:
    """Compute VADER-style compound sentiment score for a list of headlines.

    Returns a float in [-1.0, 1.0] where:
    - Positive values indicate supportive framing
    - Negative values indicate critical framing
    - Near-zero indicates neutral framing

    Uses a simplified lexicon approach: count positive and negative words,
    apply negation flipping, and normalize.
    """
    if not headlines:
        return 0.0

    total_pos = 0
    total_neg = 0
    total_words = 0

    for headline in headlines:
        words = _WORD_RE.findall(headline.lower())
        negated = False
        for word in words:
            if word in _NEGATION_WORDS:
                negated = True
                continue
            if word in _POSITIVE_WORDS:
                if negated:
                    total_neg += 1
                else:
                    total_pos += 1
                negated = False
            elif word in _NEGATIVE_WORDS:
                if negated:
                    total_pos += 1
                else:
                    total_neg += 1
                negated = False
            else:
                negated = False
            total_words += 1

    if total_words == 0:
        return 0.0

    # Normalize to [-1.0, 1.0] range
    raw = (total_pos - total_neg) / max(total_pos + total_neg, 1)
    return max(-1.0, min(1.0, raw))


def classify_framing(compound: float) -> str:
    """Map compound sentiment to framing CWE value.

    Thresholds per spec: >= 0.05 SUPPORTIVE, <= -0.05 CRITICAL, else NEUTRAL.
    """
    if compound >= 0.05:
        return "SUPPORTIVE^Supportive^FCK"
    elif compound <= -0.05:
        return "CRITICAL^Critical^FCK"
    else:
        return "NEUTRAL^Neutral^FCK"


def select_top_source(articles: list[dict], sources: list[dict]) -> tuple[str, str] | None:
    """Select the article from the highest-credibility-ranked source.

    Returns (source_name, article_url) or None if no articles.
    """
    if not articles:
        return None

    # Build a credibility lookup from source list
    rank_map: dict[str, tuple[int, str]] = {}
    for src in sources:
        sid = src.get("id", "")
        rank_map[sid] = (src.get("credibility_rank", 0), src.get("name", sid))

    best_article = articles[0]
    best_rank = 0
    best_name = ""

    for article in articles:
        source_id = (article.get("source", {}).get("id") or "").lower()
        source_name = article.get("source", {}).get("name", "")
        rank, name = rank_map.get(source_id, (0, source_name))
        if rank > best_rank:
            best_rank = rank
            best_name = name
            best_article = article

    url = best_article.get("url", "")
    name = best_name or best_article.get("source", {}).get("name", "Unknown")
    return name, url


def load_sources(sources_path: Path) -> list[dict]:
    """Load source list from JSON file."""
    with open(sources_path) as f:
        return json.load(f)


class CoverageHandler(LangGraphBase):
    """LangGraph ReAct agent for coverage-left, coverage-center, coverage-right.

    Uses the coverage @tool definitions (search_coverage, detect_coverage_framing,
    find_top_coverage_source) via an LLM-driven ReAct loop. Overrides _execute()
    to inject spectrum-specific source data into the agent's input message.

    Subclassed per-spectrum to set AGENT_NAME, spectrum label, and sources path.
    """

    SPECTRUM: str = ""
    SOURCES_FILE: str = "sources.json"

    def __init__(self, redis_config: RedisConfig | None = None) -> None:
        super().__init__(redis_config)
        self._sources: list[dict] | None = None

    def _get_sources(self) -> list[dict]:
        if self._sources is None:
            sources_path = Path(__file__).parent / self._source_dir() / self.SOURCES_FILE
            self._sources = load_sources(sources_path)
        return self._sources

    def _source_dir(self) -> str:
        """Return the directory name for this spectrum's sources."""
        return f"coverage_{self.SPECTRUM}"

    def _tools(self) -> list[BaseTool]:
        # Lazy import to avoid circular dependency with coverage_core_tools
        from swarm_reasoning.agents.coverage_core_tools import COVERAGE_TOOLS
        from swarm_reasoning.agents.observation_tools import publish_progress

        return [*COVERAGE_TOOLS, publish_progress]

    def _system_prompt(self) -> str:
        return (
            f"You are a media coverage analyzer for {self.SPECTRUM}-spectrum "
            "news sources. Your job is to search for news articles from your "
            "assigned sources, analyze their framing, and identify the most "
            "credible source.\n\n"
            "Steps:\n"
            "1. Use publish_progress to announce you are searching media sources.\n"
            "2. Call build_coverage_query with the normalized claim text to get "
            "an optimized search query.\n"
            "3. Call search_coverage with the query and the source_ids provided "
            "in the input.\n"
            "4. If articles were found, call detect_coverage_framing with the "
            "article titles as a JSON array (first 5 titles). If no articles "
            "were found, call detect_coverage_framing with \"[]\".\n"
            "5. If articles were found, call find_top_coverage_source with the "
            "articles JSON and sources JSON provided in the input.\n"
            "6. Use publish_progress to report the outcome.\n\n"
            "Call each tool exactly once in the order above. Do not fabricate "
            "results."
        )

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.COVERAGE_ARTICLE_COUNT

    def _primary_value_type(self) -> ValueType:
        return ValueType.NM

    def _timeout_value(self) -> str:
        return "0"

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        """Override to inject spectrum-specific source data into the message."""
        from langgraph.prebuilt import create_react_agent

        from swarm_reasoning.agents.prompts import TOOL_USAGE_SUFFIX
        from langchain_anthropic import ChatAnthropic

        agent_ctx = AgentContext(
            stream=stream,
            redis_client=redis_client,
            run_id=run_id,
            sk=sk,
            agent_name=self.AGENT_NAME,
        )

        # Load spectrum-specific sources
        sources = self._get_sources()
        source_ids = ",".join(s["id"] for s in sources[:20])  # NewsAPI max 20
        sources_json = json.dumps(sources)

        model = ChatAnthropic(model=self._model_id())
        tools = self._tools()
        prompt = self._system_prompt() + TOOL_USAGE_SUFFIX

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="create_react_agent has been moved",
                category=DeprecationWarning,
            )
            graph = create_react_agent(
                model=model,
                tools=tools,
                prompt=prompt,
                context_schema=AgentContext,
            )

        claim_input = _format_claim_input(context)
        message = (
            f"{claim_input}\n\n"
            f"Source IDs for search_coverage: {source_ids}\n"
            f"Sources data for find_top_coverage_source: {sources_json}"
        )

        await graph.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config={"context": agent_ctx},
        )

        # Sync observation count back to FanoutBase for STOP message
        self._seq = agent_ctx.seq_counter
