"""Check-worthiness scoring via Claude LLM with self-consistency check."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic

from swarm_reasoning.agents.claim_detector.prompts import CONFIRM_PROMPT, SCORING_PROMPT

logger = logging.getLogger(__name__)

CHECK_WORTHY_THRESHOLD = 0.4

MAX_RETRIES = 2


@dataclass
class ScoreResult:
    """Result of check-worthiness scoring."""

    score: float
    rationale: str
    proceed: bool
    passes: list[float] = field(default_factory=list)


def is_check_worthy(score: float) -> bool:
    """Apply the 0.4 threshold gate."""
    return score >= CHECK_WORTHY_THRESHOLD


def _parse_score_response(text: str) -> tuple[float, str]:
    """Parse a JSON score response from Claude.

    Returns (score, rationale). Raises ValueError on malformed input.
    """
    data = json.loads(text)
    raw_score = data["score"]
    score = float(raw_score)
    rationale = str(data.get("rationale", ""))
    return score, rationale


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    if value < lo:
        logger.warning("Score %f below range, clamping to %f", value, lo)
        return lo
    if value > hi:
        logger.warning("Score %f above range, clamping to %f", value, hi)
        return hi
    return value


async def _call_claude(client: AsyncAnthropic, prompt: str) -> str:
    """Single Claude API call returning response text."""
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def score_claim_text(
    normalized_text: str,
    client: AsyncAnthropic,
) -> ScoreResult:
    """Score a normalized claim for check-worthiness using Claude.

    Two-pass protocol:
    1. Initial scoring call
    2. Self-consistency confirmation call
    If |pass1 - pass2| > 0.1, use min(pass1, pass2) (conservative gate).

    Returns ScoreResult with final score, rationale, and proceed flag.
    """
    # Pass 1: Initial scoring
    pass1_score, pass1_rationale = await _score_with_retries(
        client,
        SCORING_PROMPT.format(claim_text=normalized_text),
    )
    passes = [pass1_score]

    # Skip pass-2 if pass-1 returned a scorer error (all retries exhausted)
    if "scorer_error" in pass1_rationale:
        return ScoreResult(
            score=pass1_score,
            rationale=pass1_rationale,
            proceed=is_check_worthy(pass1_score),
            passes=passes,
        )

    # Pass 2: Self-consistency check
    pass2_score, pass2_rationale = await _score_with_retries(
        client,
        CONFIRM_PROMPT.format(claim_text=normalized_text, score=pass1_score),
    )
    passes.append(pass2_score)

    # Resolve final score
    if abs(pass1_score - pass2_score) > 0.1:
        final_score = min(pass1_score, pass2_score)
        rationale = (
            f"Divergent scores ({pass1_score:.2f} vs {pass2_score:.2f}), "
            f"using conservative (lower): {pass2_rationale or pass1_rationale}"
        )
    else:
        final_score = pass1_score
        rationale = pass1_rationale

    return ScoreResult(
        score=final_score,
        rationale=rationale,
        proceed=is_check_worthy(final_score),
        passes=passes,
    )


async def _score_with_retries(
    client: AsyncAnthropic,
    prompt: str,
) -> tuple[float, str]:
    """Call Claude and parse JSON response, retrying up to MAX_RETRIES on malformed JSON."""
    last_error: Exception | None = None

    for attempt in range(1 + MAX_RETRIES):
        try:
            raw = await _call_claude(client, prompt)
            score, rationale = _parse_score_response(raw)
            return _clamp(score), rationale
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            last_error = exc
            logger.warning(
                "Malformed LLM response (attempt %d/%d): %s",
                attempt + 1,
                1 + MAX_RETRIES,
                exc,
            )

    # All retries exhausted — score 0.0
    logger.error("All scoring retries exhausted: %s", last_error)
    return 0.0, f"scorer_error: malformed_response ({last_error})"
