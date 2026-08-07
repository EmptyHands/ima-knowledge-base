"""RetrieverAgent 测试 - 伪向量库 + 临时 SQLite, 不依赖真实 Qdrant/网络"""
import pytest

import backend.agents.retriever_agent as retriever_module
import backend.core.retrieval as retrieval_module
from backend.core.database import get_db_session
from backend.models.database import Document


class FakeStore:
    def __init__(self, results):
        self._results = results

    async def search(self, kb_id, query, top_k=5):
        assert kb_id == "kb1"
        return self._results[:top_k]


@pytest.fixture
def sample_chunks():
    return [
        {"score": 0.81, "text": "Transformer 使用自注意力机制计算上下文", "doc_id": "doc1", "page": 3, "chunk_index": 0},
        {"score": 0.62, "text": "反向传播算法通过梯度更新权重", "doc_id": "doc2", "page": 5, "chunk_index": 1},
    ]


def test_detect_web_intent():
    assert retrieval_module.detect_web_intent("最新的行业动态是什么")
    assert retrieval_module.detect_web_intent("现在的实时行情")
    assert retrieval_module.detect_web_intent("搜索一下相关知识")
    assert retrieval_module.detect_web_intent("What is the latest news")
    assert not retrieval_module.detect_web_intent("知识库中如何实现文本分块")


@pytest.mark.asyncio
async def test_web_search_skipped_without_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert await retrieval_module.web_search("测试查询") == []


@pytest.mark.asyncio
async def test_retrieve_attaches_doc_name(app_client, monkeypatch, sample_chunks):
    db = get_db_session()
    db.add_all([
        Document(id="doc1", kb_id="kb1", filename="transformer.pdf", file_path="/tmp/t.pdf"),
        Document(id="doc2", kb_id="kb1", filename="bp.pdf", file_path="/tmp/b.pdf"),
    ])
    db.commit()
    db.close()

    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: FakeStore(sample_chunks))
    result = await retriever_module.retrieve("Transformer 是什么", "kb1", top_k=5)
    assert len(result["chunks"]) == 2
    assert result["chunks"][0]["doc_name"] == "transformer.pdf"
    assert result["chunks"][1]["doc_name"] == "bp.pdf"
    assert result["chunks"][0]["score"] == 0.81
    assert result["web_results"] == []


@pytest.mark.asyncio
async def test_web_intent_triggers_web_search(app_client, monkeypatch, sample_chunks):
    calls = []

    async def fake_web_search(query, max_results=5):
        calls.append(query)
        return [{"title": "标题", "url": "https://example.com", "snippet": "摘要"}]

    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: FakeStore(sample_chunks))
    monkeypatch.setattr(retriever_module, "web_search", fake_web_search)

    result = await retriever_module.retrieve("最新的行业动态", "kb1")
    assert calls == ["最新的行业动态"]
    assert result["web_results"][0]["url"] == "https://example.com"

    calls.clear()
    await retriever_module.retrieve("知识库如何分块", "kb1")
    assert calls == [], "无网络意图的问题不应触发网络搜索"
