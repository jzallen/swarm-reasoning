"""Temporal connection configuration."""

import os


class TemporalConfig:
    """Temporal client connection configuration, loadable from environment variables.

    TEMPORAL_ADDRESS: Temporal server address (default: localhost:7233)
    TEMPORAL_NAMESPACE: Temporal namespace (default: swarm-reasoning)
    """

    def __init__(
        self,
        address: str | None = None,
        namespace: str | None = None,
    ) -> None:
        self.address = address or os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
        self.namespace = namespace or os.environ.get("TEMPORAL_NAMESPACE", "swarm-reasoning")
