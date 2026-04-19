"""Plain implementation of the scorer's ``record_alignment`` verdict tool.

Framework-free: returns the verdict fields as a plain dict so this module
has no LangGraph / langchain imports. The ``@tool`` closure that wraps
this impl with ``Command(update=...)`` lives at the registration site
(``tasks/score_evidence/agent.py``).
"""

from __future__ import annotations

from typing import Literal

Alignment = Literal["SUPPORTS", "CONTRADICTS", "PARTIAL", "ABSENT"]


def record_alignment(alignment: Alignment, rationale: str) -> dict[str, str]:
    """Return the scorer's verdict as a plain mapping.

    Args:
        alignment: One of SUPPORTS / CONTRADICTS / PARTIAL / ABSENT.
        rationale: 1-2 sentences citing the source wording that drove
            the verdict.

    Returns:
        ``{"alignment": <verdict>, "rationale": <rationale>}``.
    """
    return {"alignment": alignment, "rationale": rationale}
