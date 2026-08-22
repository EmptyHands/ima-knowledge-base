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


@pytest.mark.asyncio
@pytest.mark.skipif(not _redis_available(), reason="需要本地 redis")
async def test_resume_across_instances(monkeypatch):
    """模拟跨实例: 图 A interrupt 挂起 → 图 B(resume)恢复成功, 状态共享

    两个 AsyncRedisSaver 连同一 redis(模拟两个 backend 实例共享 checkpointer),
    同一 thread_id: A 挂起后 B 以 Command(resume=True) 接续完成。
    """
    import redis.asyncio as aioredis
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver  # 探针实测路径

    def _saver():
        client = aioredis.Redis(host="127.0.0.1", port=6379, db=0)
        return AsyncRedisSaver(redis_client=client)

    # 复用 test_qa_graph 的 fake 模式: retrieve 有结果 + answer_agent.stream 固定输出
    import backend.agents.retriever_agent as retr_mod
    import backend.agents.answer_agent as ans_mod

    async def _ret(question, kb_id, top_k=5, force_web=False):
        return {"chunks": [{"text": "x", "doc_id": "d", "page": 1, "doc_name": "a.pdf"}],
                "web_results": []}

    async def _stream(question, history, chunks, web_results, llm=None, summary=None):
        yield {"type": "status", "data": "检索完成"}
        yield {"type": "chunk", "data": "基于片段[1]的回答"}
        yield {"type": "citations", "data": []}

    monkeypatch.setattr(retr_mod, "retrieve", _ret)
    monkeypatch.setattr(ans_mod, "stream", _stream)

    from backend.graph.qa_graph import build_graph
    from langgraph.types import Command

    cfg = {"configurable": {"thread_id": "conv-x"}}

    # 实例 A: 空库提问 → ask_user interrupt 挂起
    saver_a = _saver()
    await saver_a.adelete_thread("conv-x")  # 幂等: 清掉上次失败残留
    g_a = build_graph(saver_a)
    suspended = await g_a.ainvoke({"question": "q", "kb_id": "kb", "conv_id": "c",
                                   "kb_empty": True, "allow_web_search": False,
                                   "history": []}, cfg)
    # langgraph 1.2.11 的 ainvoke 不抛 GraphInterrupt: 中断以 __interrupt__
    # 项放进返回 state(见 test_qa_graph 同款注释)
    assert "__interrupt__" in suspended, "空库提问应触发 ask_user interrupt 挂起"
    assert suspended["__interrupt__"][0].value["text"].startswith("当前知识库还没有任何文档")

    # 实例 B: 同一 thread_id, resume 继续(独立 saver/图 = 模拟另一实例)
    saver_b = _saver()
    g_b = build_graph(saver_b)
    final = await g_b.ainvoke(Command(resume=True), cfg)
    assert final.get("answer") == "基于片段[1]的回答", "跨实例应能恢复中断并完成"

    # 清理
    await saver_a.adelete_thread("conv-x")
    tup = await saver_b.aget_tuple(cfg)
    assert tup is None
