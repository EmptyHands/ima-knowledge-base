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


class FakeHybridStore:
    """可控 dense/sparse 结果, 模拟降级触发"""

    def __init__(self, dense=None, sparse=None):
        self._dense = dense
        self._sparse = sparse

    async def search(self, kb_id, query, top_k=5):
        return (self._dense or [])[:top_k]

    async def sparse_search(self, kb_id, query, top_k=5):
        return (self._sparse or [])[:top_k]


DENSE_HIT = [{"score": 0.81, "text": "Transformer 使用自注意力", "doc_id": "doc1", "page": 3, "chunk_index": 0}]
DENSE_LOW = [{"score": 0.12, "text": "低分片段", "doc_id": "doc1", "page": 1, "chunk_index": 0}]
SPARSE_HIT = [{"score": 2.5, "text": "关键词命中片段 alpha beta", "doc_id": "doc2", "page": 2, "chunk_index": 0}]


@pytest.mark.asyncio
async def test_dense_high_score_no_fallback(app_client, monkeypatch):
    store = FakeHybridStore(dense=DENSE_HIT, sparse=SPARSE_HIT)
    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: store)
    result = await retrieval_module.vector_search("kb1", "Transformer 是什么")
    assert result[0]["doc_id"] == "doc1"
    assert result[0].get("search_type") == "dense"


@pytest.mark.asyncio
async def test_dense_empty_falls_back_to_sparse(app_client, monkeypatch):
    store = FakeHybridStore(dense=[], sparse=SPARSE_HIT)
    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: store)
    result = await retrieval_module.vector_search("kb1", "alpha beta")
    assert result[0]["doc_id"] == "doc2"
    assert result[0].get("search_type") == "sparse"


@pytest.mark.asyncio
async def test_dense_low_score_falls_back_to_sparse(app_client, monkeypatch):
    store = FakeHybridStore(dense=DENSE_LOW, sparse=SPARSE_HIT)
    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: store)
    result = await retrieval_module.vector_search("kb1", "alpha beta")
    assert result[0]["doc_id"] == "doc2"
    assert result[0].get("search_type") == "sparse"


@pytest.mark.asyncio
async def test_both_empty_returns_empty(app_client, monkeypatch):
    store = FakeHybridStore(dense=[], sparse=[])
    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: store)
    result = await retrieval_module.vector_search("kb1", "什么都不存在")
    assert result == []


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


@pytest.mark.asyncio
async def test_retrieve_force_web_triggers_web_search(app_client, monkeypatch, sample_chunks):
    calls = []

    async def fake_web_search(query, max_results=5):
        calls.append(query)
        return [{"title": "标题", "url": "https://example.com", "snippet": "摘要"}]

    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: FakeStore(sample_chunks))
    monkeypatch.setattr(retriever_module, "web_search", fake_web_search)

    # 无网络意图, 但 force_web=True 仍应触发联网
    await retriever_module.retrieve("知识库如何分块", "kb1", force_web=True)
    assert calls == ["知识库如何分块"]

    calls.clear()
    await retriever_module.retrieve("知识库如何分块", "kb1", force_web=False)
    assert calls == []
