"""Plain implementation of the discovery subagent's ``record_authoritative_domains`` tool.

Framework-free: returns the verdict fields as a plain dict so this module
has no LangGraph / langchain imports. The ``@tool`` closure that wraps
this impl with ``Command(update=...)`` lives at the registration site
(``tasks/gather_sources/agent.py``).
"""

from __future__ import annotations

MAX_DOMAINS = 20  # Sonar search_domain_filter cap: docs.perplexity.ai/guides/search-domain-filters
_ALLOWED_WINDOW = frozenset({"hour", "day", "week", "month", "year"})


def record_authoritative_domains(
    domains: list[str],
    rationale: str,
    window: str | None = None,
    after_date: str | None = None,
    before_date: str | None = None,
) -> dict:
    """Normalize the discovery subagent's domain list and recency hint.

    Args:
        domains: Raw hostnames (may carry scheme, www., or paths).
        rationale: 1-2 sentence justification from the subagent.
        window: Optional rolling-window recency: ``hour|day|week|month|year``.
        after_date: Optional ISO8601 ``YYYY-MM-DD`` lower bound.
        before_date: Optional ISO8601 ``YYYY-MM-DD`` upper bound.

    Returns:
        Plain dict with normalized ``domains`` (deduped, lowercased,
        stripped of scheme/www/paths, capped at ``MAX_DOMAINS``),
        ``rationale``, and any provided recency hint fields.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in domains:
        host = raw.strip().lower().removeprefix("https://").removeprefix("http://")
        host = host.removeprefix("www.").split("/", 1)[0]
        if host and host not in seen:
            seen.add(host)
            cleaned.append(host)
        if len(cleaned) >= MAX_DOMAINS:
            break

    update: dict = {"domains": cleaned, "rationale": rationale}
    if window and window in _ALLOWED_WINDOW:
        update["window"] = window
    if after_date:
        update["after_date"] = after_date
    if before_date:
        update["before_date"] = before_date
    return update
