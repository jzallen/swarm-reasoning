"""Shared utility functions for coverage analysis.

Provides NewsAPI query building, headline sentiment analysis (simplified
VADER-style lexicon scoring), and top-source selection by credibility rank.
Used by the coverage pipeline node (pipeline/nodes/coverage.py).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

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
