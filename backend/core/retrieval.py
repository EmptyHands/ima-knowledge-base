"""检索核心 - 三级降级检索(附文档名映射) + 意图识别 + 网络搜索"""
import logging
import os

from backend.core.config import get_config
from backend.core.database import get_db_session
from backend.core.vector_store import get_vector_store
from backend.models.database import Document

logger = logging.getLogger(__name__)

WEB_INTENT_KEYWORDS = ("最新", "现在", "实时", "网络", "搜索", "today", "news", "latest", "recent")


def detect_web_intent(question: str) -> bool:
    """判断问题是否需要触发网络搜索"""
    q = question.lower()
    return any(kw in q for kw in WEB_INTENT_KEYWORDS)


async def vector_search(kb_id: str, question: str, top_k: int | None = None) -> list[dict]:
    """三级降级检索: dense → (空/低分) → sparse → 空

    返回 [{score, text, doc_id, page, chunk_index, doc_name, search_type}]
    """
    config = get_config()
    top_k = top_k or config.retrieval_top_k
    store = get_vector_store()

    dense = await store.search(kb_id, question, top_k=top_k)
    if dense and dense[0]["score"] >= config.retrieval_dense_threshold:
        return _attach_doc_names(dense, "dense")

    sparse = await store.sparse_search(kb_id, question, top_k=top_k)
    if sparse:
        return _attach_doc_names(sparse, "sparse")
    return []


def _attach_doc_names(chunks: list[dict], search_type: str) -> list[dict]:
    """补充 doc_name 文档名与 search_type 标记"""
    doc_ids = {c["doc_id"] for c in chunks}
    db = get_db_session()
    try:
        rows = db.query(Document.id, Document.filename).filter(Document.id.in_(doc_ids)).all()
        name_map = {row.id: row.filename for row in rows}
    finally:
        db.close()
    return [{**c, "doc_name": name_map.get(c["doc_id"], ""), "search_type": search_type} for c in chunks]


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """网络搜索 (Tavily), 未配置 TAVILY_API_KEY 时跳过

    返回 [{title, url, snippet}]
    """
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        logger.warning("未配置 TAVILY_API_KEY, 跳过网络搜索")
        return []
    try:
        from tavily import AsyncTavilyClient
    except ImportError:
        logger.warning("tavily-python 未安装, 跳过网络搜索")
        return []
    try:
        client = AsyncTavilyClient(api_key=api_key)
        response = await client.search(query=query, max_results=max_results, search_depth="basic")
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in response.get("results", [])
        ]
    except Exception as e:
        logger.error(f"网络搜索失败: {e}")
        return []
