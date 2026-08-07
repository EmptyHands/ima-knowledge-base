"""文档处理服务 - 上传/解析/入库状态机"""
import logging
import os
import uuid
from pathlib import Path

from backend.core.config import get_config
from backend.core.database import get_db_session
from backend.core.vector_store import get_vector_store
from backend.models.database import Document, KnowledgeBase
from backend.services.chunker import chunk_pages
from backend.utils.file_parser import parse_file

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


def save_upload(user_id: str, kb_id: str, filename: str, content: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的文件格式: {ext}")
    if len(content) > MAX_FILE_SIZE:
        raise ValueError("文件超过 20MB 限制")
    config = get_config()
    dir_path = Path(config.storage_dir) / user_id / kb_id
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / f"{uuid.uuid4().hex}{ext}"
    file_path.write_bytes(content)
    return str(file_path)


async def process_document(document_id: str):
    """后台任务: 解析 → 分块 → 向量化 → 更新状态"""
    db = get_db_session()
    try:
        doc = db.get(Document, document_id)
        if not doc:
            return
        doc.status = "processing"
        db.commit()

        result = parse_file(doc.file_path)
        if not result.get("success"):
            doc.status = "failed"
            doc.error_msg = result.get("error", "解析失败")
            db.commit()
            return

        pages = result.get("pages", [])
        if not pages:
            doc.status = "failed"
            doc.error_msg = "文档无可用文本内容(可能是扫描件)"
            db.commit()
            return

        chunks = chunk_pages(pages)
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
        user_id = kb.user_id if kb else ""

        count = await get_vector_store().add_documents(
            kb_id=doc.kb_id, doc_id=doc.id, user_id=user_id, chunks=chunks,
        )
        doc.status = "ready"
        doc.page_count = result.get("page_count", 0)
        doc.chunk_count = count
        db.commit()
        logger.info(f"Document {doc.id} processed: {count} chunks")
    except Exception as e:
        logger.exception(f"Document processing failed: {document_id}")
        try:
            doc = db.get(Document, document_id)
            doc.status = "failed"
            doc.error_msg = str(e)[:500]
            db.commit()
        except Exception:
            pass
    finally:
        db.close()
