"""Claim text normalization: lowercasing, hedging removal, pronoun resolution.

This is a pure function -- no I/O, no LLM calls. The normalization pipeline
runs in strict order: lowercase -> hedge removal -> pronoun resolution ->
whitespace normalization -> truncation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_NORMALIZED_LENGTH = 200

# ---------------------------------------------------------------------------
# Hedging phrase lexicon (compiled at module load, not per-call)
# Order matters: longer/more specific patterns first to avoid partial matches.
# ---------------------------------------------------------------------------

_HEDGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Multi-word patterns first (most specific)
    (re.compile(r"\bunconfirmed\s+reports\s+(?:say|suggest|indicate)\b"), ""),
    (re.compile(r"\baccording\s+to\s+sources\b"), ""),
    # "source(s) close to <noun phrase>" — remove through the noun
    (re.compile(r"\bsources?\s+close\s+to\s+(?:the\s+|a\s+|an\s+)?\w+\b"), ""),
    (re.compile(r"\bit\s+is\s+claimed\s+that\b"), ""),
    (re.compile(r"\bsources\s+say\b"), ""),
    (re.compile(r"\bsome\s+say\b"), ""),
    # Single-word patterns
    (re.compile(r"\breportedly\b"), ""),
    (re.compile(r"\ballegedly\b"), ""),
    (re.compile(r"\bpurportedly\b"), ""),
    (re.compile(r"\bapparently\b"), ""),
    (re.compile(r"\bseemingly\b"), ""),
]

# Punctuation artifact cleanup patterns
_COMMA_ARTIFACT = re.compile(r",\s*,")
_DOT_ARTIFACT = re.compile(r"\.\s*\.")
_LEADING_COMMA = re.compile(r"^\s*,\s*")
_MULTI_SPACE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Pronoun resolution patterns (compiled once at module load)
# ---------------------------------------------------------------------------
_RE_HE = re.compile(r"\bhe\b")
_RE_SHE = re.compile(r"\bshe\b")
_RE_IT = re.compile(r"\bit\b")
_RE_THEY = re.compile(r"\bthey\b")


@dataclass
class NormalizeResult:
    """Result of claim text normalization."""

    normalized: str
    hedges_removed: list[str] = field(default_factory=list)
    pronouns_resolved: bool = False
    fallback_used: bool = False


def normalize_claim_text(
    raw_text: str,
    entity_persons: list[str] | None = None,
    entity_orgs: list[str] | None = None,
) -> NormalizeResult:
    """Normalize claim text through the four-step pipeline.

    Args:
        raw_text: The original claim text.
        entity_persons: Named person entities from the ingestion stream.
        entity_orgs: Named org entities from the ingestion stream.

    Returns:
        NormalizeResult with normalized text and metadata.
    """
    # Step 1: Unicode-aware lowercasing
    text = raw_text.casefold()

    # Step 2: Hedging language removal
    hedges_removed: list[str] = []
    for pattern, replacement in _HEDGE_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            hedges_removed.extend(matches)
            text = pattern.sub(replacement, text)

    # Step 3: Opportunistic pronoun resolution
    pronouns_resolved = False

    persons = entity_persons or []
    orgs = entity_orgs or []

    # he/she -> single person entity
    if len(persons) == 1:
        person_name = persons[0].casefold()
        for pronoun_re in (_RE_HE, _RE_SHE):
            new_text = pronoun_re.sub(person_name, text)
            if new_text != text:
                pronouns_resolved = True
                text = new_text

    # it -> single org entity
    if len(orgs) == 1:
        org_name = orgs[0].casefold()
        new_text = _RE_IT.sub(org_name, text)
        if new_text != text:
            pronouns_resolved = True
            text = new_text

    # they -> resolve only if exactly one person XOR one org (ambiguous otherwise)
    if len(persons) == 1 and len(orgs) == 0:
        new_text = _RE_THEY.sub(persons[0].casefold(), text)
        if new_text != text:
            pronouns_resolved = True
            text = new_text
    elif len(orgs) == 1 and len(persons) == 0:
        new_text = _RE_THEY.sub(orgs[0].casefold(), text)
        if new_text != text:
            pronouns_resolved = True
            text = new_text

    # Step 4: Whitespace normalization and punctuation artifact cleanup
    text = _MULTI_SPACE.sub(" ", text).strip()
    text = _COMMA_ARTIFACT.sub(",", text)
    text = _DOT_ARTIFACT.sub(".", text)
    text = _LEADING_COMMA.sub("", text)
    text = text.strip()

    # Empty-output fallback
    fallback_used = False
    if not text:
        text = raw_text.casefold()
        fallback_used = True

    # Truncation at word boundary with "..." suffix
    if len(text) > MAX_NORMALIZED_LENGTH:
        truncated = text[: MAX_NORMALIZED_LENGTH - 3]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]
        text = truncated + "..."

    return NormalizeResult(
        normalized=text,
        hedges_removed=hedges_removed,
        pronouns_resolved=pronouns_resolved,
        fallback_used=fallback_used,
    )
