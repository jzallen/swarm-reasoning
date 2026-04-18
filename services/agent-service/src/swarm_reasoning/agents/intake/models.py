"""Typed I/O models for the intake agent.

IntakeInput carries the URL submission pre-extracted from PipelineState.
IntakeOutput carries the full intake result across both phases:
  Phase A: article fetch + claim decomposition
  Phase B: domain classification + entity extraction on selected claim
"""

from __future__ import annotations

from typing_extensions import TypedDict


class IntakeInput(TypedDict):
    """Input to the intake agent, translated from PipelineState.

    Fields are pre-extracted by the pipeline node from PipelineState so the
    agent has no coupling to PipelineState directly.
    """

    url: str
    """Source URL submitted by the user."""


class Attribution(TypedDict, total=False):
    """Per-claim in-text attribution (rhetorical, not publisher).

    Populated only when the article body attributes a specific claim to a
    named external source (e.g. 'according to CNBC'). Absent when the
    article simply makes the claim itself.
    """

    attributed_source: str | None
    """Named source credited within the article (e.g. 'CNBC', 'Associated Press')."""

    attribution_phrase: str | None
    """Verbatim attribution clause from the article body."""


class ExtractedClaimDict(TypedDict):
    """A single factual claim extracted from article text (dict form)."""

    index: int
    """Claim index (1-5)."""

    claim_text: str
    """Standalone verifiable sentence."""

    quote: str
    """Single best sentence from the article making or supporting the claim."""

    attribution: Attribution | None
    """In-text attribution to an external source, or None if the article makes
    the claim without such attribution. Never the article's own publisher."""


class IntakeOutput(TypedDict, total=False):
    """Output from the intake agent, translated to PipelineState updates.

    Phase A fields (URL -> claims) are populated after fetch + decompose.
    Phase B fields (selected claim -> analysis) are populated after user
    selects a claim and the agent runs classify + extract.

    On rejection (bad URL, no claims, fetch error), only ``error`` is set.
    Uses ``total=False`` so phases can populate fields incrementally.
    """

    # Phase A: article fetch + claim decomposition
    article_text: str
    """Extracted article body text from the source URL."""

    article_title: str
    """Title of the source article."""

    article_author: str | None
    """Byline of the article, if extractable."""

    article_publisher: str
    """Name of the publication (sitename, JSON-LD publisher, or hostname fallback)."""

    article_published_at: str | None
    """Publication timestamp (ISO-8601), if extractable."""

    article_accessed_at: str
    """ISO-8601 UTC timestamp of the original network fetch. Cache hits
    replay this original stamp rather than the replay time."""

    extracted_claims: list[ExtractedClaimDict]
    """Up to 5 factual claims extracted from the article."""

    # Phase B: selected claim analysis
    selected_claim: ExtractedClaimDict
    """The claim chosen by the user for fact-checking."""

    domain: str
    """Domain classification (HEALTHCARE, ECONOMICS, POLICY, SCIENCE,
    ELECTION, CRIME, OTHER)."""

    entities: dict[str, list[str]]
    """Extracted entities keyed by type (persons, organizations, dates,
    locations, statistics)."""

    # Error (rejection path)
    error: str
    """Error code on rejection (e.g. URL_UNREACHABLE, NO_FACTUAL_CLAIMS).
    Absent on success."""
