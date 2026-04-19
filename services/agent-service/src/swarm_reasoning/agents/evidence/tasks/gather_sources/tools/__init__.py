"""Plain-function @tool delegate impls for the source-discovery subagent."""

from swarm_reasoning.agents.evidence.tasks.gather_sources.tools import (
    record_authoritative_domains as _module,
)

record_authoritative_domains = _module.record_authoritative_domains

__all__ = ["record_authoritative_domains"]
