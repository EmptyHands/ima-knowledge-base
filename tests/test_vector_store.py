"""VectorStore 测试 - 使用确定性伪向量,不依赖 Ollama/网络"""
import hashlib
import pytest
from qdrant_client.models import Distance, VectorParams

from backend.core.vector_store import VectorStore

TEST_COLLECTION = "ima_kb_test"


@pytest.fixture
def store(monkeypatch):
    vs = VectorStore()
    vs.collection_name = TEST_COLLECTION
    try:
        vs.client.delete_collection(TEST_COLLECTION)
    except Exception:
        pass
    vs.client.create_collection(
        collection_name=TEST_COLLECTION,
        vectors_config=VectorParams(size=vs._embed_dim, distance=Distance.COSINE),
    )

    async def fake_embed(text: str) -> list[float]:
        h = hashlib.md5(text.encode("utf-8")).digest()
        v = list(h * (vs._embed_dim // 16 + 1))[:vs._embed_dim]
        norm = sum(x * x for x in v) ** 0.5
        return [x / norm for x in v]

    monkeypatch.setattr(vs, "_embed", fake_embed)
    yield vs
    try:
        vs.client.delete_collection(TEST_COLLECTION)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_add_and_search_self_match(store):
    """自检索:相同文本向量 cosine=1,应排第一"""
    await store.add_documents(
        kb_id="kb1", doc_id="doc1", user_id="u1",
        chunks=[
            {"text": "Transformer 使用自注意力机制计算上下文", "page": 3, "chunk_index": 0},
            {"text": "反向传播算法通过梯度更新权重", "page": 5, "chunk_index": 0},
        ],
    )
    results = await store.search("kb1", "Transformer 使用自注意力机制计算上下文", top_k=5)
    assert len(results) >= 1
    assert results[0]["doc_id"] == "doc1"
    assert results[0]["page"] == 3
    assert results[0]["text"].startswith("Transformer")


@pytest.mark.asyncio
async def test_search_filtered_by_kb(store):
    await store.add_documents(
        kb_id="kbA", doc_id="docA", user_id="u1",
        chunks=[{"text": "只有 A 库独有的内容 alpha beta gamma", "page": 1, "chunk_index": 0}],
    )
    await store.add_documents(
        kb_id="kbB", doc_id="docB", user_id="u1",
        chunks=[{"text": "只有 B 库独有的内容 alpha beta gamma", "page": 2, "chunk_index": 0}],
    )
    results = await store.search("kbA", "只有 A 库独有的内容 alpha beta gamma", top_k=5)
    assert results, "应在 kbA 检索到结果"
    assert all(r["doc_id"] == "docA" for r in results), "检索结果应只来自 kbA"


@pytest.mark.asyncio
async def test_delete_document(store):
    await store.add_documents(
        kb_id="kb1", doc_id="doc1", user_id="u1",
        chunks=[{"text": "将被删除的文档内容 qwerty", "page": 1, "chunk_index": 0}],
    )
    await store.add_documents(
        kb_id="kb1", doc_id="doc2", user_id="u1",
        chunks=[{"text": "保留的文档内容 qwerty", "page": 2, "chunk_index": 0}],
    )
    await store.delete_document("doc1")
    results = await store.search("kb1", "将被删除的文档内容 qwerty", top_k=5)
    assert all(r["doc_id"] != "doc1" for r in results), "doc1 向量应被删除"
    kept = await store.search("kb1", "保留的文档内容 qwerty", top_k=5)
    assert kept and kept[0]["doc_id"] == "doc2"
