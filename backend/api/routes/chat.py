"""会话与消息路由 - SSE 流式问答 (RetrieverAgent → AnswerAgent 管线)"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.agents import answer_agent, retriever_agent
from backend.api.routes.auth import get_current_user
from backend.core.database import get_db
from backend.models.database import Conversation, KnowledgeBase, Message, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/conversations", tags=["会话"])

HISTORY_LIMIT = 10


class ConvCreate(BaseModel):
    kb_id: str
    title: str = "新对话"


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
              req: AskRequest,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """SSE 流式问答: status → chunk* → citations → done / error (PRD §6.2)"""
    conv = _get_owned_conv(db, conv_id, user)
    question = req.question.strip()

    history_rows = db.query(Message).filter(Message.conversation_id == conv_id) \
        .order_by(Message.created_at.desc()).limit(HISTORY_LIMIT).all()
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    user_msg = Message(conversation_id=conv_id, role="user", content=question)
    db.add(user_msg)
    db.commit()

    async def gen():
        try:
            yield _sse("status", {"text": "正在检索知识库..."})
            retrieval = await retriever_agent.retrieve(question, conv.kb_id)
            chunks, web_results = retrieval["chunks"], retrieval["web_results"]
            if not chunks:
                yield _sse("status", {"text": "知识库中未检索到相关内容, 将基于已有知识作答"})

            answer_parts = []
            citations = []
            async for event in answer_agent.stream(question, history, chunks, web_results):
                if event["type"] == "chunk":
                    answer_parts.append(event["data"])
                    yield _sse("chunk", {"text": event["data"]})
                elif event["type"] == "citations":
                    citations = event["data"]
                else:
                    yield _sse("status", {"text": event["data"]})

            assistant_msg = Message(conversation_id=conv_id, role="assistant",
                                    content="".join(answer_parts),
                                    citations_json=citations or None)
            db.add(assistant_msg)
            if conv.title == "新对话":
                conv.title = question[:20]
            db.commit()

            yield _sse("citations", {"items": citations})
            yield _sse("done", {"message_id": assistant_msg.id})
        except Exception as e:
            logger.exception("问答管线失败")
            yield _sse("error", {"text": f"生成失败: {str(e)[:200]}"})

    return StreamingResponse(gen(), media_type="text/event-stream")
