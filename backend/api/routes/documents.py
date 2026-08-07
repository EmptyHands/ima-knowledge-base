"""文档路由 - 上传/列表/删除(含解析状态机)"""
import os
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.vector_store import get_vector_store
from backend.models.database import Document, KnowledgeBase, User
from backend.api.routes.auth import get_current_user
from backend.services.document_service import save_upload, process_document

router = APIRouter(prefix="/api/v1/documents", tags=["文档"])


def _check_kb_owned(db: Session, kb_id: str, user: User) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user.id
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@router.post("")
async def upload_documents(kb_id: str = Query(...),
                           background_tasks: BackgroundTasks = None,
                           files: list[UploadFile] = File(...),
                           db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    _check_kb_owned(db, kb_id, user)
    results = []
    for f in files:
        content = await f.read()
        try:
            existing = db.query(Document).filter(
                Document.kb_id == kb_id,
                Document.filename == f.filename,
                Document.file_size == len(content),
            ).first()
            if existing:
                results.append({"filename": f.filename, "duplicate": True})
                continue
            file_path = save_upload(user.id, kb_id, f.filename, content)
            doc = Document(kb_id=kb_id, filename=f.filename, file_path=file_path,
                           file_size=len(content), status="pending")
            db.add(doc)
            db.commit()
            db.refresh(doc)
            background_tasks.add_task(process_document, doc.id)
            results.append({"id": doc.id, "filename": f.filename, "status": "pending"})
        except ValueError as e:
            results.append({"filename": f.filename, "error": str(e)})
    return results


@router.get("")
def list_documents(kb_id: str = Query(...),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _check_kb_owned(db, kb_id, user)
    return db.query(Document).filter(Document.kb_id == kb_id) \
        .order_by(Document.created_at.desc()).all()


@router.delete("/{doc_id}")
async def delete_document(doc_id: str,
                          db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).join(KnowledgeBase).filter(
        KnowledgeBase.user_id == user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    await get_vector_store().delete_document(doc_id)
    try:
        os.remove(doc.file_path)
    except OSError:
        pass
    db.delete(doc)
    db.commit()
    return {"ok": True}
