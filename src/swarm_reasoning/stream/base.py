"""Abstract ReasoningStream interface (ADR-012)."""

from abc import ABC, abstractmethod

from swarm_reasoning.models.stream import StreamMessage


class ReasoningStream(ABC):
    """Abstract interface for the observation stream transport.

    Implementations must be append-only: no delete or modify operations.
    The Redis Streams backend is the default; a Kafka backend is the
    production graduation path (ADR-012).
    """

    @abstractmethod
    async def publish(self, stream_key: str, message: StreamMessage) -> str:
        """Publish a message to the stream. Returns the stream entry ID."""
        ...

    @abstractmethod
    async def read(self, stream_key: str, last_id: str = "0") -> list[StreamMessage]:
        """Read messages from the stream starting after last_id."""
        ...

    @abstractmethod
    async def read_range(
        self, stream_key: str, start: str = "-", end: str = "+"
    ) -> list[StreamMessage]:
        """Read messages in an ID range (inclusive)."""
        ...

    @abstractmethod
    async def read_latest(self, stream_key: str) -> StreamMessage | None:
        """Read the most recent message from the stream, or None if empty."""
        ...

    @abstractmethod
    async def list_streams(self, run_id: str) -> list[str]:
        """List all stream keys for a given run ID."""
        ...

    @abstractmethod
    async def health(self) -> bool:
        """Check if the transport backend is healthy."""
        ...
