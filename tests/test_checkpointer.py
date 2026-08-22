"""DEV-019: checkpointer 工厂 — redis 不可用时降级 MemorySaver"""
import pytest


def _redis_available():
    try:
        from redis import Redis
        return Redis(host="127.0.0.1", port=6379, socket_connect_timeout=1).ping()
    except Exception:
        return False


def test_redis_unreachable_falls_back_to_memory(monkeypatch):
    """指向无效端口 → 返回 MemorySaver 且打警告"""
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", "6399")  # 无服务端口
    import backend.core.config as config_module
    config_module._config = None

    from backend.graph import qa_graph
    saver = qa_graph._create_checkpointer()
    from langgraph.checkpoint.memory import MemorySaver
    assert isinstance(saver, MemorySaver)


@pytest.mark.asyncio
@pytest.mark.skipif(not _redis_available(), reason="需要本地 redis")
async def test_redis_reachable_returns_redis_saver(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", "6379")
    import backend.core.config as config_module
    config_module._config = None

    from backend.graph import qa_graph
    saver = qa_graph._create_checkpointer()
    # 探针实测: AsyncRedisSaver 与同步 RedisSaver 是兄弟类(共享 BaseRedisSaver)
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    assert isinstance(saver, AsyncRedisSaver)
