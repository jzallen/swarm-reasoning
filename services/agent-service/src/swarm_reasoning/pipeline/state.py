"""PipelineState -- typed inter-node data plane for the claim verification pipeline.

Each pipeline node reads from PipelineState and returns a dict of state updates
that LangGraph merges. Observations flow through state, not Redis Streams.
Redis is still used for SSE observation publishing as a side-effect.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict


class PipelineState(TypedDict, total=False):
    """Typed state for the claim verification pipeline.

    Required at pipeline start: claim_text, run_id, session_id.
    All other fields are populated by nodes as they execute.
    List fields (observations, errors) use the ``add`` reducer so
    parallel branches append rather than overwrite.
    """

    # --- Input (provided at pipeline invocation) ---
    claim_text: str
    claim_url: str | None
    submission_date: str
    run_id: str
    session_id: str

    # --- Intake Phase A output (URL → claims) ---
    article_text: str
    article_title: str
    extracted_claims: list[dict]  # up to 5 ExtractedClaimDict items

    # --- Intake Phase B input (user selection) ---
    selected_claim: dict  # ExtractedClaimDict chosen by the user

    # --- Intake Phase B output (claim analysis) ---
    claim_domain: str
    entities: dict[str, list[str]]  # {persons: [...], orgs: [...], ...}
    is_check_worthy: bool

    # --- Evidence output ---
    claimreview_matches: list[dict]
    domain_sources: list[dict]
    evidence_confidence: float | None

    # --- Coverage output ---
    coverage_left: list[dict]
    coverage_center: list[dict]
    coverage_right: list[dict]
    framing_analysis: dict

    # --- Validation output ---
    validated_urls: list[dict]
    convergence_score: float
    citations: list[dict]
    blindspot_score: float
    blindspot_direction: str

    # --- Synthesizer output ---
    verdict: str
    confidence: float
    narrative: str
    verdict_observations: list[dict]

    # --- Metadata (appended by multiple nodes via ``add`` reducer) ---
    observations: Annotated[list[dict], add]
    errors: Annotated[list[str], add]
