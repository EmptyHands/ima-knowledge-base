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
