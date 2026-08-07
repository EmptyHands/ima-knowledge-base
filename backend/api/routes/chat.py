"""会话与消息路由 - 占位流式(Task 16 接入真 SSE)"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.models.database import Conversation, KnowledgeBase, Message, User
from backend.api.routes.auth import get_current_user

router = APIRouter(prefix="/api/v1/conversations", tags=["会话"])


class ConvCreate(BaseModel):
    kb_id: str
    title: str = "新对话"


def _check_kb_owned(db: Session, kb_id: str, user: User) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user.id
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


def _get_owned_conv(db: Session, conv_id: str, user: User) -> Conversation:
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id, Conversation.user_id == user.id
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


@router.get("")
def list_conversations(kb_id: str,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    _check_kb_owned(db, kb_id, user)
    return db.query(Conversation).filter(
        Conversation.kb_id == kb_id, Conversation.user_id == user.id
    ).order_by(Conversation.updated_at.desc()).all()


@router.post("")
def create_conversation(req: ConvCreate,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    _check_kb_owned(db, req.kb_id, user)
    conv = Conversation(kb_id=req.kb_id, user_id=user.id, title=req.title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/{conv_id}")
def delete_conversation(conv_id: str,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    conv = _get_owned_conv(db, conv_id, user)
    db.delete(conv)
    db.commit()
    return {"ok": True}


@router.get("/{conv_id}/messages")
def list_messages(conv_id: str,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    _get_owned_conv(db, conv_id, user)
    return db.query(Message).filter(Message.conversation_id == conv_id) \
        .order_by(Message.created_at.asc()).all()


@router.post("/{conv_id}/messages")
async def ask(conv_id: str,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """占位流: W3 接入多 Agent 问答管线"""
    _get_owned_conv(db, conv_id, user)

    async def gen():
        yield 'event: status\ndata: {"text": "回答生成中, W3 接入多 Agent 管线"}\n\n'
        yield 'event: done\ndata: {"message_id": null}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")
