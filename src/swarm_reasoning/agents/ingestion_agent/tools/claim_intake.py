"""claim-intake tool: validates claims and publishes CLAIM_* observations."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from redis.asyncio import Redis

from swarm_reasoning.agents.ingestion_agent.validation import (
    ValidationError,
    check_duplicate,
    normalize_date,
    validate_claim_text,
    validate_source_url,
)
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.status import EpistemicStatus
from swarm_reasoning.models.stream import ObsMessage, Phase, StartMessage, StopMessage
from swarm_reasoning.stream.base import ReasoningStream
from swarm_reasoning.stream.key import stream_key

AGENT_NAME = "ingestion-agent"


class IngestionResult(BaseModel):
    """Result from the ingest_claim tool."""

    accepted: bool
    run_id: str
    rejection_reason: str | None = None
    normalized_date: str | None = None


class StreamPublishError(Exception):
    """Raised when a Redis Stream publish fails."""


class StreamNotOpenError(Exception):
    """Raised when attempting to START an already-open stream."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_obs(
    run_id: str,
    seq: int,
    code: ObservationCode,
    value: str,
    status: EpistemicStatus,
    note: str | None = None,
) -> ObsMessage:
    return ObsMessage(
        observation=Observation(
            runId=run_id,
            agent=AGENT_NAME,
            seq=seq,
            code=code,
            value=value,
            valueType=ValueType.ST,
            status=status.value,
            timestamp=_now_iso(),
            method="ingest_claim",
            note=note,
        )
    )


async def _publish_progress(redis_client: Redis, run_id: str, message: str) -> None:
    """Publish a progress event to progress:{runId} stream."""
    await redis_client.xadd(
        f"progress:{run_id}",
        {"agent": AGENT_NAME, "message": message, "timestamp": _now_iso()},
    )


async def ingest_claim(
    run_id: str,
    claim_text: str,
    source_url: str | None = None,
    source_date: str | None = None,
    *,
    stream: ReasoningStream,
    redis_client: Redis,
) -> IngestionResult:
    """Validate a claim and publish CLAIM_TEXT/URL/DATE observations.

    On success, leaves the stream open for classify_domain to close.
    On rejection, publishes STOP with finalStatus=X.
    """
    sk = stream_key(run_id, AGENT_NAME)

    # Check for already-open stream (double-START guard)
    existing = await stream.read_latest(sk)
    if existing is not None:
        raise StreamNotOpenError(f"Stream {sk} already has messages; cannot re-start")

    # Publish START
    try:
        await stream.publish(
            sk,
            StartMessage(
                runId=run_id,
                agent=AGENT_NAME,
                phase=Phase.INGESTION,
                timestamp=_now_iso(),
            ),
        )
    except Exception as exc:
        raise StreamPublishError(f"Failed to publish START: {exc}") from exc

    # Publish progress: validating
    await _publish_progress(redis_client, run_id, "Validating claim submission...")

    # Run validation
    normalized = None
    try:
        validate_claim_text(claim_text)
        if source_url is not None:
            validate_source_url(source_url)
        if source_date is not None:
            normalized = normalize_date(source_date)
        is_dup = await check_duplicate(redis_client, run_id, claim_text)
        if is_dup:
            raise ValidationError("DUPLICATE_CLAIM_IN_RUN")
    except ValidationError as ve:
        # Rejection path: X-status CLAIM_TEXT + STOP
        obs = _make_obs(
            run_id,
            1,
            ObservationCode.CLAIM_TEXT,
            claim_text.strip(),
            EpistemicStatus.CANCELLED,
            note=ve.reason,
        )
        await stream.publish(sk, obs)
        await stream.publish(
            sk,
            StopMessage(
                runId=run_id,
                agent=AGENT_NAME,
                finalStatus="X",
                observationCount=1,
                timestamp=_now_iso(),
            ),
        )
        await _publish_progress(redis_client, run_id, f"Claim rejected: {ve.reason}")
        return IngestionResult(accepted=False, run_id=run_id, rejection_reason=ve.reason)

    # Success path: publish three F-status observations
    stripped = claim_text.strip()
    seq = 1
    await stream.publish(
        sk,
        _make_obs(run_id, seq, ObservationCode.CLAIM_TEXT, stripped, EpistemicStatus.FINAL),
    )

    seq += 1
    await stream.publish(
        sk,
        _make_obs(
            run_id,
            seq,
            ObservationCode.CLAIM_SOURCE_URL,
            source_url or "",
            EpistemicStatus.FINAL,
        ),
    )

    seq += 1
    await stream.publish(
        sk,
        _make_obs(
            run_id,
            seq,
            ObservationCode.CLAIM_SOURCE_DATE,
            normalized or "",
            EpistemicStatus.FINAL,
        ),
    )

    await _publish_progress(redis_client, run_id, "Claim accepted, classifying domain...")

    return IngestionResult(accepted=True, run_id=run_id, normalized_date=normalized)
