"""Intake pipeline node (M1.1): claim validation, domain classification,
normalization, check-worthiness scoring, and entity extraction.

Consolidates logic from three legacy agent handlers (ingestion_agent,
claim_detector, entity_extractor) into a single LangGraph node with
fixed execution order:

    1. ingest_claim  — structural validation, CLAIM_TEXT/URL/DATE observations
    2. classify_domain — LLM domain classification, CLAIM_DOMAIN observation
    3. normalize_claim — text normalization, CLAIM_NORMALIZED observation
    4. score_check_worthiness — LLM scoring + gate, CHECK_WORTHY_SCORE observation
    5. extract_entities — LLM NER, ENTITY_* observations

All observations are published as side-effects via PipelineContext.
State updates are returned as a dict for LangGraph to merge.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from anthropic import AsyncAnthropic
from langgraph.types import RunnableConfig

from swarm_reasoning.agents.entity_extraction import (
    EntityExtractionResult,
    extract_entities_llm,
)
from swarm_reasoning.pipeline.nodes.intake_domain import (
    DOMAIN_VOCABULARY,
    build_prompt,
    call_claude,
)
from swarm_reasoning.pipeline.nodes.intake_normalizer import normalize_claim_text
from swarm_reasoning.pipeline.nodes.intake_scorer import score_claim_text
from swarm_reasoning.pipeline.nodes.intake_validation import (
    ValidationError,
    check_duplicate,
    normalize_date,
    validate_claim_text,
    validate_source_url,
)
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState
from swarm_reasoning.temporal.errors import MissingApiKeyError

logger = logging.getLogger(__name__)

AGENT_NAME = "intake"

# Deterministic entity publish order (PERSON -> ORG -> DATE -> LOCATION -> STATISTIC)
_ENTITY_ORDER: list[tuple[str, ObservationCode]] = [
    ("persons", ObservationCode.ENTITY_PERSON),
    ("organizations", ObservationCode.ENTITY_ORG),
    ("dates", ObservationCode.ENTITY_DATE),
    ("locations", ObservationCode.ENTITY_LOCATION),
    ("statistics", ObservationCode.ENTITY_STATISTIC),
]


def _get_anthropic_client() -> AsyncAnthropic:
    """Create an AsyncAnthropic client from the environment."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise MissingApiKeyError("ANTHROPIC_API_KEY is required for intake node")
    return AsyncAnthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Tool 1: ingest_claim — validate claim and publish CLAIM_TEXT/URL/DATE
# ---------------------------------------------------------------------------


async def _ingest_claim(
    ctx: PipelineContext,
    claim_text: str,
    claim_url: str | None,
    submission_date: str | None,
) -> tuple[bool, str | None, str | None]:
    """Validate the claim and publish CLAIM_TEXT/URL/DATE observations.

    Returns (accepted, rejection_reason, normalized_date).
    """
    await ctx.publish_progress(AGENT_NAME, "Validating claim submission...")

    normalized_date: str | None = None
    try:
        validate_claim_text(claim_text)
        if claim_url is not None:
            validate_source_url(claim_url)
        if submission_date is not None:
            normalized_date = normalize_date(submission_date)
        is_dup = await check_duplicate(ctx.redis_client, ctx.run_id, claim_text)
        if is_dup:
            raise ValidationError("DUPLICATE_CLAIM_IN_RUN")
    except ValidationError as ve:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CLAIM_TEXT,
            value=claim_text.strip(),
            value_type=ValueType.ST,
            status="X",
            method="ingest_claim",
            note=ve.reason,
        )
        await ctx.publish_progress(AGENT_NAME, f"Claim rejected: {ve.reason}")
        return False, ve.reason, None

    # Publish accepted observations
    stripped = claim_text.strip()
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_TEXT,
        value=stripped,
        value_type=ValueType.ST,
        method="ingest_claim",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_SOURCE_URL,
        value=claim_url or "",
        value_type=ValueType.ST,
        method="ingest_claim",
    )
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_SOURCE_DATE,
        value=normalized_date or "",
        value_type=ValueType.ST,
        method="ingest_claim",
    )

    await ctx.publish_progress(AGENT_NAME, "Claim accepted, classifying domain...")
    return True, None, normalized_date


# ---------------------------------------------------------------------------
# Tool 2: classify_domain — LLM-powered domain classification
# ---------------------------------------------------------------------------


async def _classify_domain(
    ctx: PipelineContext,
    claim_text: str,
    client: AsyncAnthropic,
) -> str:
    """Classify the claim's domain using Claude and publish CLAIM_DOMAIN.

    Returns the domain string (e.g. "HEALTHCARE", "ECONOMICS").
    Falls back to "OTHER" if LLM returns unrecognized values.
    """
    import anthropic as anthropic_lib

    domain: str | None = None

    for attempt in range(2):
        try:
            prompt = build_prompt(claim_text, retry=(attempt > 0))
            result = await call_claude(client, prompt)
        except (anthropic_lib.AuthenticationError, anthropic_lib.APIConnectionError, anthropic_lib.RateLimitError) as exc:
            logger.warning("Domain classification API error (attempt %d): %s", attempt + 1, exc)
            continue

        if result in DOMAIN_VOCABULARY:
            domain = result
            break

    if domain is not None:
        # Publish preliminary then final
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CLAIM_DOMAIN,
            value=domain,
            value_type=ValueType.ST,
            status="P",
            method="classify_domain",
        )
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CLAIM_DOMAIN,
            value=domain,
            value_type=ValueType.ST,
            method="classify_domain",
        )
    else:
        domain = "OTHER"
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CLAIM_DOMAIN,
            value="OTHER",
            value_type=ValueType.ST,
            method="classify_domain",
            note="LLM returned unrecognized value after 2 attempts; fallback applied",
        )

    await ctx.publish_progress(AGENT_NAME, f"Domain classified: {domain}")
    return domain


# ---------------------------------------------------------------------------
# Tool 3: normalize_claim — text normalization
# ---------------------------------------------------------------------------


async def _normalize_claim(
    ctx: PipelineContext,
    claim_text: str,
) -> str:
    """Normalize the claim text and publish CLAIM_NORMALIZED.

    Returns the normalized claim string.
    """
    result = normalize_claim_text(claim_text)

    note = None
    if result.fallback_used:
        note = "normalization: fallback to raw text"
    if result.hedges_removed:
        hedge_note = f"hedges removed: {', '.join(result.hedges_removed[:3])}"
        note = f"{note}; {hedge_note}" if note else hedge_note

    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CLAIM_NORMALIZED,
        value=result.normalized,
        value_type=ValueType.ST,
        method="normalize_claim",
        note=note,
    )

    await ctx.publish_progress(AGENT_NAME, "Claim normalized, scoring check-worthiness...")
    return result.normalized


# ---------------------------------------------------------------------------
# Tool 4: score_check_worthiness — LLM scoring with gate decision
# ---------------------------------------------------------------------------


async def _score_check_worthiness(
    ctx: PipelineContext,
    normalized_text: str,
    client: AsyncAnthropic,
) -> tuple[float, bool]:
    """Score check-worthiness and publish CHECK_WORTHY_SCORE observations.

    Returns (score, proceed).
    """
    score_result = await score_claim_text(normalized_text, client)

    score_note = (
        f"LLM rationale: {score_result.rationale[:480]}"
        if score_result.rationale
        else None
    )

    # Publish preliminary score (pass-1) if available
    if score_result.passes:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CHECK_WORTHY_SCORE,
            value=f"{score_result.passes[0]:.2f}",
            value_type=ValueType.NM,
            status="P",
            method="score_claim",
            note=score_note,
            units="score",
            reference_range="0.0-1.0",
        )

    # Publish final resolved score
    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CHECK_WORTHY_SCORE,
        value=f"{score_result.score:.2f}",
        value_type=ValueType.NM,
        method="score_claim",
        note=score_note,
        units="score",
        reference_range="0.0-1.0",
    )

    if score_result.proceed:
        await ctx.publish_progress(
            AGENT_NAME,
            f"Check-worthy (score: {score_result.score:.2f}), extracting entities...",
        )
    else:
        await ctx.publish_progress(
            AGENT_NAME,
            f"Not check-worthy (score: {score_result.score:.2f}), skipping to synthesis",
        )

    return score_result.score, score_result.proceed


# ---------------------------------------------------------------------------
# Tool 5: extract_entities — LLM-powered named entity recognition
# ---------------------------------------------------------------------------


async def _extract_entities(
    ctx: PipelineContext,
    normalized_claim: str,
    client: AsyncAnthropic,
) -> dict[str, list[str]]:
    """Extract entities via LLM and publish ENTITY_* observations.

    Returns the entities dict matching PipelineState.entities shape.
    """
    from swarm_reasoning.agents._utils import (
        normalize_date as normalize_entity_date,
    )

    result = await extract_entities_llm(normalized_claim, client)

    # Publish entity observations in deterministic order
    for field_name, obs_code in _ENTITY_ORDER:
        entities: list[str] = getattr(result, field_name)
        for entity_value in entities:
            value = entity_value
            note: str | None = None

            if obs_code == ObservationCode.ENTITY_DATE:
                value, note = normalize_entity_date(entity_value)

            await ctx.publish_observation(
                agent=AGENT_NAME,
                code=obs_code,
                value=value,
                value_type=ValueType.ST,
                method="extract_entities",
                note=note,
            )

    entity_count = sum(
        len(getattr(result, field_name)) for field_name, _ in _ENTITY_ORDER
    )
    await ctx.publish_progress(AGENT_NAME, f"Extracted {entity_count} entities")

    return {
        "persons": result.persons,
        "organizations": result.organizations,
        "dates": result.dates,
        "locations": result.locations,
        "statistics": result.statistics,
    }


# ---------------------------------------------------------------------------
# Main node function
# ---------------------------------------------------------------------------


async def intake_node(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Intake pipeline node: validate, classify, normalize, score, extract.

    Executes 5 tools in fixed order. Returns state updates for LangGraph
    to merge into PipelineState.
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat("intake")

    claim_text = state["claim_text"]
    claim_url = state.get("claim_url")
    submission_date = state.get("submission_date")

    # Tool 1: Validate claim
    accepted, rejection_reason, _ = await _ingest_claim(
        ctx, claim_text, claim_url, submission_date,
    )
    if not accepted:
        return {
            "is_check_worthy": False,
            "errors": [f"Claim rejected: {rejection_reason}"],
        }

    ctx.heartbeat("intake")

    # Tool 2: Classify domain
    client = _get_anthropic_client()
    domain = await _classify_domain(ctx, claim_text, client)

    ctx.heartbeat("intake")

    # Tool 3: Normalize claim
    normalized = await _normalize_claim(ctx, claim_text)

    ctx.heartbeat("intake")

    # Tool 4: Score check-worthiness
    score, proceed = await _score_check_worthiness(ctx, normalized, client)

    ctx.heartbeat("intake")

    if not proceed:
        return {
            "normalized_claim": normalized,
            "claim_domain": domain,
            "check_worthy_score": score,
            "is_check_worthy": False,
        }

    # Tool 5: Extract entities
    entities = await _extract_entities(ctx, normalized, client)

    return {
        "normalized_claim": normalized,
        "claim_domain": domain,
        "check_worthy_score": score,
        "entities": entities,
        "is_check_worthy": True,
    }
