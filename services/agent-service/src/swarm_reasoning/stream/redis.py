"""Redis Streams implementation of ReasoningStream (ADR-012)."""

from __future__ import annotations

import redis.asyncio as aioredis
from pydantic import TypeAdapter

from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.stream import StreamMessage
from swarm_reasoning.stream.base import ReasoningStream

_message_adapter = TypeAdapter(StreamMessage)


def _serialize(message: StreamMessage) -> dict[str, str]:
    """Serialize a StreamMessage to a Redis stream entry."""
    return {"data": _message_adapter.dump_json(message, by_alias=True).decode()}


def _deserialize(data: dict[bytes, bytes]) -> StreamMessage:
    """Deserialize a Redis stream entry to a StreamMessage."""
    raw = data[b"data"]
    return _message_adapter.validate_json(raw)


class RedisReasoningStream(ReasoningStream):
    """Redis Streams backend for observation transport.

    Uses XADD (publish), XREAD (read), XRANGE (read_range).
    No XDEL, XTRIM, or DEL operations — append-only (ADR-003).
    """

    def __init__(self, config: RedisConfig | None = None) -> None:
        cfg = config or RedisConfig()
        self._redis = aioredis.Redis(host=cfg.host, port=cfg.port, db=cfg.db)

    async def close(self) -> None:
        """Close the Redis connection."""
        await self._redis.aclose()

    async def publish(self, stream_key: str, message: StreamMessage) -> str:
        entry_id: bytes = await self._redis.xadd(stream_key, _serialize(message))
        return entry_id.decode()

    async def read(self, stream_key: str, last_id: str = "0") -> list[StreamMessage]:
        # XREAD returns list of [stream_name, [(id, data), ...]]
        result = await self._redis.xread({stream_key: last_id})
        if not result:
            return []
        messages: list[StreamMessage] = []
        for _stream_name, entries in result:
            for _entry_id, data in entries:
                messages.append(_deserialize(data))
        return messages

    async def read_range(
        self, stream_key: str, start: str = "-", end: str = "+"
    ) -> list[StreamMessage]:
        entries = await self._redis.xrange(stream_key, min=start, max=end)
        return [_deserialize(data) for _entry_id, data in entries]

    async def read_latest(self, stream_key: str) -> StreamMessage | None:
        entries = await self._redis.xrevrange(stream_key, count=1)
        if not entries:
            return None
        _entry_id, data = entries[0]
        return _deserialize(data)

    async def list_streams(self, run_id: str) -> list[str]:
        pattern = f"reasoning:{run_id}:*"
        keys: list[str] = []
        async for key in self._redis.scan_iter(match=pattern):
            keys.append(key.decode() if isinstance(key, bytes) else key)
        return sorted(keys)

    async def health(self) -> bool:
        try:
            return await self._redis.ping()
        except Exception:
            return False
