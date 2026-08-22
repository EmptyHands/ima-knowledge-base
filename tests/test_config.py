"""配置测试 - 新增检索阈值项"""
import backend.core.config as config_module


def test_retrieval_dense_threshold_default(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_DENSE_THRESHOLD", raising=False)
    config_module._config = None
    cfg = config_module.get_config()
    assert cfg.retrieval_dense_threshold == 0.35


def test_retrieval_dense_threshold_from_env(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_DENSE_THRESHOLD", "0.5")
    config_module._config = None
    cfg = config_module.get_config()
    assert cfg.retrieval_dense_threshold == 0.5


def test_redis_defaults(monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_PORT", raising=False)
    monkeypatch.delenv("REDIS_DB", raising=False)
    config_module._config = None
    cfg = config_module.get_config()
    assert cfg.redis_host == "localhost"
    assert cfg.redis_port == 6379
    assert cfg.redis_db == 0


def test_redis_from_env(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_DB", "2")
    config_module._config = None
    cfg = config_module.get_config()
    assert cfg.redis_host == "redis"
    assert cfg.redis_port == 6380
    assert cfg.redis_db == 2
