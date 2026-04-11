"""Configuration for Redis connection."""

import os


class RedisConfig:
    """Redis connection configuration, loadable from environment variables."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        db: int | None = None,
    ) -> None:
        self.host = host or os.environ.get("REDIS_HOST", "localhost")
        self.port = port or int(os.environ.get("REDIS_PORT", "6379"))
        self.db = db if db is not None else int(os.environ.get("REDIS_DB", "0"))
