"""Intake agent module -- claim validation, domain classification, normalization,
check-worthiness scoring, and entity extraction.

Exposes the intake agent builder, its state-to-output projection, and
typed I/O models for use by the pipeline node wrapper in
``swarm_reasoning.pipeline.nodes.intake``.
"""

from swarm_reasoning.agents.intake.agent import (
    IntakeAgentState,
    build_intake_agent,
    intake_output_from_state,
)
from swarm_reasoning.agents.intake.models import IntakeInput, IntakeOutput

__all__ = [
    "IntakeAgentState",
    "IntakeInput",
    "IntakeOutput",
    "build_intake_agent",
    "intake_output_from_state",
]
