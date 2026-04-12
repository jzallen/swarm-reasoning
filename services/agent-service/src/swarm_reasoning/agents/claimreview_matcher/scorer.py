"""TF-IDF cosine similarity scorer for ClaimReview matching.

Implements a lightweight TF-IDF + cosine similarity computation using only
stdlib (no scikit-learn dependency). Scores how well a ClaimReview's
claimReviewed text matches the submitted normalized claim.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Common English stop words to exclude from TF-IDF vectors
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "because",
        "if",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "he",
        "she",
        "they",
        "them",
        "his",
        "her",
        "their",
        "my",
        "your",
        "our",
        "about",
        "up",
        "out",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def _tokenize(text: str) -> list[str]:
    """Lowercase and tokenize, removing stop words."""
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOP_WORDS]


def cosine_similarity(text_a: str, text_b: str) -> float:
    """Compute TF-IDF-weighted cosine similarity between two texts.

    Uses term frequency vectors (IDF approximated from the two-document corpus).
    Returns a score in [0.0, 1.0].
    """
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    tf_a = Counter(tokens_a)
    tf_b = Counter(tokens_b)

    # Build vocabulary and compute IDF (2-document corpus)
    vocab = set(tf_a) | set(tf_b)
    doc_count = {}
    for term in vocab:
        doc_count[term] = (1 if term in tf_a else 0) + (1 if term in tf_b else 0)

    # TF-IDF vectors
    def tfidf_vector(tf: Counter) -> dict[str, float]:
        total = sum(tf.values())
        vec = {}
        for term in vocab:
            tf_val = tf.get(term, 0) / total if total > 0 else 0
            idf_val = math.log(2 / doc_count[term]) + 1  # smoothed IDF
            vec[term] = tf_val * idf_val
        return vec

    vec_a = tfidf_vector(tf_a)
    vec_b = tfidf_vector(tf_b)

    # Cosine similarity
    dot = sum(vec_a[t] * vec_b[t] for t in vocab)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return max(0.0, min(1.0, dot / (norm_a * norm_b)))
