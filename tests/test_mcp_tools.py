"""MCP 内置工具测试 - monkeypatch 底层检索 + 临时 SQLite"""
import pytest

from backend.mcp.registry import ToolError, registry


@pytest.mark.asyncio
async def test_web_search_tool(monkeypatch):
    from backend.core import retrieval
    calls = {}

    async def fake_web_search(query, max_results=5):
        calls["query"] = query
        calls["max_results"] = max_results
        return [{"title": "T", "url": "https://a.com", "snippet": "s"}]

    monkeypatch.setattr(retrieval, "web_search", fake_web_search)
    result = await registry.call("web_search", {"query": "最新动态", "max_results": 3})
    assert calls == {"query": "最新动态", "max_results": 3}
    assert result["results"][0]["url"] == "https://a.com"


@pytest.mark.asyncio
async def test_web_search_default_max_results(monkeypatch):
    from backend.core import retrieval
    seen = {}

    async def fake_web_search(query, max_results=5):
        seen["max_results"] = max_results
        return []

    monkeypatch.setattr(retrieval, "web_search", fake_web_search)
    await registry.call("web_search", {"query": "q"})
    assert seen["max_results"] == 5


class FakeStore:
    def __init__(self, results):
        self._results = results

    async def search(self, kb_id, query, top_k=5):
        return self._results[:top_k]


@pytest.mark.asyncio
async def test_vector_search_tool(app_client, monkeypatch):
    from backend.core import retrieval
    from backend.core.database import get_db_session
    from backend.models.database import Document
    db = get_db_session()
    db.add(Document(id="doc1", kb_id="kb1", filename="t.pdf", file_path="/tmp/t.pdf"))
    db.commit()
    db.close()

    monkeypatch.setattr(retrieval, "get_vector_store", lambda: FakeStore([
        {"score": 0.81, "text": "Transformer 使用自注意力", "doc_id": "doc1", "page": 3, "chunk_index": 0},
    ]))
    result = await registry.call("vector_search", {"kb_id": "kb1", "question": "Transformer 是什么", "top_k": 5})
    assert result["chunks"][0]["doc_name"] == "t.pdf"
    assert result["chunks"][0]["search_type"] == "dense"


@pytest.mark.asyncio
async def test_kb_status_tool(app_client):
    from backend.core.database import get_db_session
    from backend.models.database import Document, KnowledgeBase
    db = get_db_session()
    db.add(KnowledgeBase(id="kb-1", user_id="u1", name="测试库"))
    db.add_all([
        Document(id="d1", kb_id="kb-1", filename="a.pdf", file_path="/tmp/a.pdf",
                 status="ready", chunk_count=10),
        Document(id="d2", kb_id="kb-1", filename="b.pdf", file_path="/tmp/b.pdf",
                 status="processing", chunk_count=0),
    ])
    db.commit()
    db.close()

    result = await registry.call("kb_status", {"kb_id": "kb-1"})
    assert result == {"kb_id": "kb-1", "name": "测试库", "document_count": 2,
                      "ready_count": 1, "chunk_count": 10}


@pytest.mark.asyncio
async def test_kb_status_missing_kb(app_client):
    with pytest.raises(ToolError, match="知识库不存在"):
        await registry.call("kb_status", {"kb_id": "nope"})
