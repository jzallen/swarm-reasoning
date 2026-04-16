"""Domain classification utilities for the intake agent.

Provides the controlled vocabulary and prompt builder for classifying
a claim into one of seven domain categories.
"""

from __future__ import annotations

DOMAIN_VOCABULARY: frozenset[str] = frozenset(
    {"HEALTHCARE", "ECONOMICS", "POLICY", "SCIENCE", "ELECTION", "CRIME", "OTHER"}
)


def build_prompt(claim_text: str, retry: bool = False) -> list[dict]:
    """Build Anthropic messages for domain classification."""
    user_content = f"Claim: {claim_text}"
    if retry:
        user_content += (
            "\n\nNote: your previous response was not recognized. "
            "You must respond with exactly one of: "
            "HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER"
        )
    return [{"role": "user", "content": user_content}]
