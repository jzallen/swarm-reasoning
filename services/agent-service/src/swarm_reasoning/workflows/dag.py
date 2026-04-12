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


# The static DAG: four phases mapping to three run states.
# Phase 2a (parallel fan-out) and 2b (source validation) both map to "analyzing".
DAG: tuple[Phase, ...] = (
    Phase(
        id="1",
        name="ingestion",
        agents=("ingestion-agent", "claim-detector", "entity-extractor"),
        mode=PhaseMode.SEQUENTIAL,
    ),
    Phase(
        id="2a",
        name="fanout",
        agents=(
            "claimreview-matcher",
            "coverage-left",
            "coverage-center",
            "coverage-right",
            "domain-evidence",
        ),
        mode=PhaseMode.PARALLEL,
    ),
    Phase(
        id="2b",
        name="fanout-validation",
        agents=("source-validator",),
        mode=PhaseMode.SEQUENTIAL,
    ),
    Phase(
        id="3",
        name="synthesis",
        agents=("blindspot-detector", "synthesizer"),
        mode=PhaseMode.SEQUENTIAL,
    ),
)

ALL_AGENTS: tuple[str, ...] = tuple(agent for phase in DAG for agent in phase.agents)
