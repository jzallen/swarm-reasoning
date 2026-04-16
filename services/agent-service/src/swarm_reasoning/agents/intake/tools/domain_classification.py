"""Domain classification utilities for the intake agent.

Provides the controlled vocabulary, prompt builder, and Claude API call
for classifying a claim into one of seven domain categories.
"""

from __future__ import annotations

DOMAIN_VOCABULARY: frozenset[str] = frozenset(
    {"HEALTHCARE", "ECONOMICS", "POLICY", "SCIENCE", "ELECTION", "CRIME", "OTHER"}
)

_SYSTEM_PROMPT = (
    "You are a domain classifier for a fact-checking system. "
    "Your task is to categorize the given claim into exactly one of the following domains:\n\n"
    "HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER\n\n"
    "Respond with exactly one word -- the domain code. "
    "Do not include punctuation, explanation, or any other text."
)

_RETRY_SUFFIX = (
    "\n\nNote: your previous response was not recognized. "
    "You must respond with exactly one of: "
    "HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER"
)


def build_prompt(claim_text: str, retry: bool = False) -> list[dict]:
    """Build Anthropic messages for domain classification."""
    user_content = f"Claim: {claim_text}"
    if retry:
        user_content += _RETRY_SUFFIX
    return [{"role": "user", "content": user_content}]
