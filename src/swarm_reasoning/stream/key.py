"""Stream key generation for Redis Streams."""


def stream_key(run_id: str, agent: str) -> str:
    """Generate a Redis Stream key for an agent's observation stream.

    Format: reasoning:{runId}:{agent}
    """
    return f"reasoning:{run_id}:{agent}"
