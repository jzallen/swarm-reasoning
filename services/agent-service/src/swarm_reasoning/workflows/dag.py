"""Three-phase DAG definition for the claim verification pipeline (ADR-0016)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PhaseMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass(frozen=True)
class Phase:
    """A single phase in the execution DAG."""

    id: str
    name: str
    agents: tuple[str, ...]
    mode: PhaseMode


# The static DAG: three phases mapping to three run states.
DAG: tuple[Phase, ...] = (
    Phase(
        id="1",
        name="ingestion",
        agents=("ingestion-agent", "claim-detector", "entity-extractor"),
        mode=PhaseMode.SEQUENTIAL,
    ),
    Phase(
        id="2",
        name="fanout",
        agents=(
            "evidence",
            "coverage-left",
            "coverage-center",
            "coverage-right",
        ),
        mode=PhaseMode.PARALLEL,
    ),
    Phase(
        id="3",
        name="synthesis",
        agents=("validation", "synthesizer"),
        mode=PhaseMode.SEQUENTIAL,
    ),
)

ALL_AGENTS: tuple[str, ...] = tuple(agent for phase in DAG for agent in phase.agents)
