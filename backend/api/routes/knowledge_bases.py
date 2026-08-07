"""知识库路由 - CRUD + 用户隔离"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.vector_store import get_vector_store
from backend.models.database import KnowledgeBase, User
from backend.api.routes.auth import get_current_user

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["知识库"])


class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class KBUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


def _get_owned_kb(db: Session, kb_id: str, user: User) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user.id
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@router.get("")
def list_kbs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(KnowledgeBase).filter(KnowledgeBase.user_id == user.id) \
        .order_by(KnowledgeBase.created_at.desc()).all()


@router.get("/{kb_id}")
def get_kb(kb_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _get_owned_kb(db, kb_id, user)


@router.post("")
def create_kb(req: KBCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    kb = KnowledgeBase(user_id=user.id, name=req.name, description=req.description)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


@router.put("/{kb_id}")
def update_kb(kb_id: str, req: KBUpdate, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    kb = _get_owned_kb(db, kb_id, user)
    kb.name = req.name
    kb.description = req.description
    db.commit()
    db.refresh(kb)
    return kb


@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    kb = _get_owned_kb(db, kb_id, user)
    await get_vector_store().delete_knowledge_base(kb_id)
    db.delete(kb)
    db.commit()
    return {"ok": True}
