"""DEV-012: langgraph 问答管线节点单测 - 不依赖 HTTP, 直接驱动图"""
import pytest


class FakeRetrieve:
    def __init__(self):
        self.calls = []

    async def __call__(self, question, kb_id, top_k=5, force_web=False):
        self.calls.append((question, kb_id, force_web))
        return {"chunks": [], "web_results": []}


@pytest.fixture()
def fake_retrieve(monkeypatch):
    fake = FakeRetrieve()
    import backend.agents.retriever_agent as m
    monkeypatch.setattr(m, "retrieve", fake)
    return fake


def _input(question="怎么种苹果", kb_id="kb1", conv_id="conv1",
           kb_empty=False, allow_web_search=False, history=None):
    return {"question": question, "kb_id": kb_id, "conv_id": conv_id,
            "kb_empty": kb_empty, "allow_web_search": allow_web_search,
            "history": history or []}


@pytest.mark.asyncio
async def test_retrieve_node_calls_agent_and_routes(fake_retrieve):
    """检索节点: 调用 retriever_agent.retrieve, 关键词意图置 allow_web_search=True"""
    from backend.graph.qa_graph import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    g = build_graph(MemorySaver())
    final = await g.ainvoke(_input(question="最新 agent 技术有哪些"),
                            {"configurable": {"thread_id": "t1"}})
    assert fake_retrieve.calls[-1] == ("最新 agent 技术有哪些", "kb1", False)
    assert final["allow_web_search"] is True, "关键词意图应打开联网开关"


@pytest.mark.asyncio
async def test_retrieve_no_keyword_keeps_web_disabled(fake_retrieve):
    from backend.graph.qa_graph import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    g = build_graph(MemorySaver())
    final = await g.ainvoke(_input(), {"configurable": {"thread_id": "t2"}})
    assert final["allow_web_search"] is False
    assert fake_retrieve.calls[-1] == ("怎么种苹果", "kb1", False)
