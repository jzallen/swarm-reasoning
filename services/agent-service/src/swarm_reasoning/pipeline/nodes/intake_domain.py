"""Re-export shim -- canonical location is now agents.intake.tools.domain_classification."""

from swarm_reasoning.agents.intake.tools.domain_classification import (  # noqa: F401
    _SYSTEM_PROMPT,
    DOMAIN_VOCABULARY,
    build_prompt,
)

__all__ = [
    "DOMAIN_VOCABULARY",
    "_SYSTEM_PROMPT",
    "build_prompt",
]
