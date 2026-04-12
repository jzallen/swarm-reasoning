"""Unit tests for RedisConfig."""

from swarm_reasoning.config import RedisConfig


class TestRedisConfig:
    def test_defaults(self):
        cfg = RedisConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 6379
        assert cfg.db == 0

    def test_explicit_values(self):
        cfg = RedisConfig(host="redis", port=6380, db=1)
        assert cfg.host == "redis"
        assert cfg.port == 6380
        assert cfg.db == 1

    def test_environment_override(self, monkeypatch):
        monkeypatch.setenv("REDIS_HOST", "redis-server")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_DB", "2")
        cfg = RedisConfig()
        assert cfg.host == "redis-server"
        assert cfg.port == 6380
        assert cfg.db == 2
