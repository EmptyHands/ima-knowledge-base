"""向量对账测试 - DB 状态 ready 但 Qdrant 无向量的文档自动重建索引 (DEV-006)"""
import pytest

from backend.core.database import get_db_session
from backend.models.database import Document, KnowledgeBase, User
from backend.services.document_service import reconcile_missing_vectors
from tests.test_e2e_flow import fake_embed  # noqa: F401 确定性伪向量, 不依赖 Ollama

DOC_TEXT = "Transformer 使用自注意力机制计算上下文, 这是核心原理。"


@pytest.fixture()
def ready_doc(tmp_path, app_client):
    """创建 user/kb/ready 文档(磁盘上有可解析的 md 文件), 返回 doc_id"""
    path = tmp_path / "reconcile.md"
    path.write_text(DOC_TEXT, encoding="utf-8")
    db = get_db_session()
    user = User(username="recon", password_hash="x")
    db.add(user)
    db.flush()
    kb = KnowledgeBase(user_id=user.id, name="对账测试库")
    db.add(kb)
    db.flush()
    doc = Document(kb_id=kb.id, filename="reconcile.md", file_path=str(path),
                   file_size=path.stat().st_size, status="ready", chunk_count=1)
    db.add(doc)
    db.commit()
    doc_id = doc.id
    db.close()
    return doc_id


def _count_points(doc_id: str) -> int:
    from backend.core.vector_store import get_vector_store
    store = get_vector_store()
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    return store.client.count(
        collection_name=store.collection_name,
        count_filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
        exact=True,
    ).count


@pytest.mark.asyncio
async def test_reconcile_reindexes_ready_doc_without_vectors(ready_doc, fake_embed):
    assert _count_points(ready_doc) == 0
    stats = await reconcile_missing_vectors()
    assert stats["total"] == 1
    assert stats["reindexed"] == 1
    assert stats["skipped"] == 0
    assert stats["failed"] == 0
    assert _count_points(ready_doc) >= 1
    db = get_db_session()
    doc = db.get(Document, ready_doc)
    assert doc.status == "ready"
    assert doc.chunk_count >= 1
    db.close()


@pytest.mark.asyncio
async def test_reconcile_skips_doc_with_existing_vectors(ready_doc, fake_embed):
    await reconcile_missing_vectors()
    assert _count_points(ready_doc) >= 1
    stats = await reconcile_missing_vectors()
    assert stats["total"] == 1
    assert stats["reindexed"] == 0
    assert stats["skipped"] == 1


@pytest.mark.asyncio
async def test_reconcile_ignores_non_ready_docs(ready_doc, fake_embed):
    db = get_db_session()
    doc = db.get(Document, ready_doc)
    doc.status = "failed"
    doc.error_msg = "模拟失败"
    db.commit()
    db.close()
    stats = await reconcile_missing_vectors()
    assert stats["total"] == 0
    assert stats["reindexed"] == 0
    assert _count_points(ready_doc) == 0
