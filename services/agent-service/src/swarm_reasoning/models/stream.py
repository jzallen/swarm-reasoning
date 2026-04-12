"""Stream message types: START, OBS, STOP (observation-schema-spec.md Section 2)."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from swarm_reasoning.models.observation import Observation


class Phase(str, Enum):
    INGESTION = "ingestion"
    FANOUT = "fanout"
    SYNTHESIS = "synthesis"


class StartMessage(BaseModel):
    """Published when an agent begins reasoning for a run."""

    type: Literal["START"] = "START"
    run_id: str = Field(alias="runId")
    agent: str
    phase: Phase
    timestamp: str

    model_config = {"populate_by_name": True}


class ObsMessage(BaseModel):
    """Published for each observation finding."""

    type: Literal["OBS"] = "OBS"
    observation: Observation


class StopMessage(BaseModel):
    """Published when an agent completes reasoning for a run."""

    type: Literal["STOP"] = "STOP"
    run_id: str = Field(alias="runId")
    agent: str
    final_status: Literal["F", "X"] = Field(alias="finalStatus")
    observation_count: Annotated[int, Field(ge=0)] = Field(alias="observationCount")
    timestamp: str

    model_config = {"populate_by_name": True}


StreamMessage = Annotated[
    Union[StartMessage, ObsMessage, StopMessage],
    Field(discriminator="type"),
]
