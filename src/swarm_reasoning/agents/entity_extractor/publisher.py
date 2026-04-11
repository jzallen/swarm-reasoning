"""Observation publishing for the entity-extractor agent."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from swarm_reasoning.agents.entity_extractor.extractor import EntityExtractionResult
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.status import EpistemicStatus
from swarm_reasoning.models.stream import ObsMessage, Phase, StartMessage, StopMessage
from swarm_reasoning.stream.base import ReasoningStream
from swarm_reasoning.stream.key import stream_key

AGENT_NAME = "entity-extractor"

# Deterministic entity publish order per spec
_ENTITY_ORDER: list[tuple[str, ObservationCode]] = [
    ("persons", ObservationCode.ENTITY_PERSON),
    ("organizations", ObservationCode.ENTITY_ORG),
    ("dates", ObservationCode.ENTITY_DATE),
    ("locations", ObservationCode.ENTITY_LOCATION),
    ("statistics", ObservationCode.ENTITY_STATISTIC),
]

# Regex for valid date formats
_DATE_YYYYMMDD = re.compile(r"^\d{8}$")
_DATE_RANGE = re.compile(r"^\d{8}-\d{8}$")
_YEAR_ONLY = re.compile(r"^\d{4}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_date(date_str: str) -> tuple[str, str | None]:
    """Normalize a date string to YYYYMMDD or YYYYMMDD-YYYYMMDD format.

    Returns (normalized_value, note) where note is "date-not-normalized"
    if the string cannot be parsed, None otherwise.
    """
    stripped = date_str.strip()

    if _DATE_YYYYMMDD.match(stripped):
        return stripped, None

    if _DATE_RANGE.match(stripped):
        return stripped, None

    if _YEAR_ONLY.match(stripped):
        return f"{stripped}0101-{stripped}1231", None

    return stripped, "date-not-normalized"


async def publish_entities(
    run_id: str,
    result: EntityExtractionResult,
    stream: ReasoningStream,
) -> int:
    """Publish START, entity observations, and STOP to the agent's stream.

    Entities are published in deterministic order:
    PERSON -> ORG -> DATE -> LOCATION -> STATISTIC.

    Returns the total count of OBS messages published.
    """
    sk = stream_key(run_id, AGENT_NAME)

    # START
    await stream.publish(
        sk,
        StartMessage(
            runId=run_id,
            agent=AGENT_NAME,
            phase=Phase.INGESTION,
            timestamp=_now_iso(),
        ),
    )

    seq = 0

    for field_name, obs_code in _ENTITY_ORDER:
        entities: list[str] = getattr(result, field_name)
        for entity_value in entities:
            seq += 1
            value = entity_value
            note: str | None = None

            if obs_code == ObservationCode.ENTITY_DATE:
                value, note = normalize_date(entity_value)

            await stream.publish(
                sk,
                ObsMessage(
                    observation=Observation(
                        runId=run_id,
                        agent=AGENT_NAME,
                        seq=seq,
                        code=obs_code,
                        value=value,
                        valueType=ValueType.ST,
                        status=EpistemicStatus.FINAL.value,
                        timestamp=_now_iso(),
                        method="extract_entities",
                        note=note,
                    ),
                ),
            )

    # STOP
    await stream.publish(
        sk,
        StopMessage(
            runId=run_id,
            agent=AGENT_NAME,
            finalStatus="F",
            observationCount=seq,
            timestamp=_now_iso(),
        ),
    )

    return seq


async def publish_error_stop(
    run_id: str,
    stream: ReasoningStream,
) -> None:
    """Publish STOP with finalStatus='X' after a failed extraction."""
    sk = stream_key(run_id, AGENT_NAME)
    await stream.publish(
        sk,
        StopMessage(
            runId=run_id,
            agent=AGENT_NAME,
            finalStatus="X",
            observationCount=0,
            timestamp=_now_iso(),
        ),
    )
