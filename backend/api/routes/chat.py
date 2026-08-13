"""会话与消息路由 - SSE 流式问答 (RetrieverAgent → AnswerAgent 管线)"""
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.agents import answer_agent, retriever_agent
from backend.api.routes.auth import get_current_user
from backend.core.database import get_db
from backend.models.database import Conversation, Document, KnowledgeBase, Message, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/conversations", tags=["会话"])

HISTORY_LIMIT = 10

EMPTY_KB_FALLBACK = "当前知识库还没有任何文档。知识库中未找到与『{question}』相关的内容。是否需要联网搜索?回复『需要』即可。"
NO_RESULT_FALLBACK = "知识库中未找到与『{question}』相关的内容。是否需要联网搜索?回复『需要』即可。"
NO_ANSWER_FALLBACK = "未能基于检索内容生成回答。知识库中未找到与『{question}』相关的内容。是否需要联网搜索?回复『需要』即可。"
WEB_UNAVAILABLE = "联网搜索当前不可用(未配置 TAVILY_API_KEY), 请换个问法或上传相关文档后重试。"
CONFIRM_WORDS = ("需要", "要", "好", "是", "可以", "联网", "搜索", "用")
_RE_FALLBACK_QUESTION = re.compile(r"未找到与『(.+?)』相关的内容")


def _confirm_question(history: list[dict], question: str) -> tuple[str, bool]:
    """反问确认识别: 最近助手消息是反问模板且本次回复为确认词时, 返回(原问题, True)"""
    q = question.strip().strip("。.!！?？ ")
    last_assistant = next((m for m in reversed(history) if m["role"] == "assistant"), None)
    if last_assistant:
        m = _RE_FALLBACK_QUESTION.search(last_assistant["content"] or "")
        if m and q in CONFIRM_WORDS:
            return m.group(1), True
    return question, False


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
    _check_kb_owned(db, conv.kb_id, user)
    question = req.question.strip()

    history_rows = db.query(Message).filter(Message.conversation_id == conv_id) \
        .order_by(Message.created_at.desc()).limit(HISTORY_LIMIT).all()
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    doc_count = db.query(Document).filter(Document.kb_id == conv.kb_id).count()
    question, force_web = _confirm_question(history, question)

    user_msg = Message(conversation_id=conv_id, role="user", content=req.question.strip())
    db.add(user_msg)
    db.commit()

    async def _finish_fallback(text: str):
        """反问/不可用回复: 固定文本以 chunk 流式下发 + 入库 + citations + done, 不调用大模型

        chunk 事件必不可少: 前端仅累积 chunk 内容, 无 chunk 则答案不会渲染, 需刷新才能看到
        """
        assistant_msg = Message(conversation_id=conv_id, role="assistant",
                                content=text, citations_json=None)
        db.add(assistant_msg)
        if conv.title == "新对话":
            conv.title = text[:20]
        db.commit()
        yield _sse("chunk", {"text": text})
        yield _sse("citations", {"items": []})
        yield _sse("done", {"message_id": assistant_msg.id})

    async def gen():
        try:
            if doc_count == 0 and not force_web:
                text = EMPTY_KB_FALLBACK.format(question=question)
                yield _sse("status", {"text": "知识库为空, 未进行检索"})
                async for ev in _finish_fallback(text):
                    yield ev
                return

            yield _sse("status", {"text": "正在检索知识库..."})
            retrieval = await retriever_agent.retrieve(question, conv.kb_id, force_web=force_web)
            chunks, web_results = retrieval["chunks"], retrieval["web_results"]
            if not chunks and not web_results:
                if force_web:
                    text = WEB_UNAVAILABLE
                else:
                    text = NO_RESULT_FALLBACK.format(question=question)
                yield _sse("status", {"text": "知识库中未检索到相关内容"})
                async for ev in _finish_fallback(text):
                    yield ev
                return

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

            answer = "".join(answer_parts).strip()
            if not answer:
                # LLM 未输出任何内容(如无法依据检索片段回答时流式返回空): 不落空消息,
                # 与无结果分支一致回退为反问, 避免刷新后出现空白气泡
                yield _sse("status", {"text": "未能生成有效回答"})
                async for ev in _finish_fallback(NO_ANSWER_FALLBACK.format(question=question)):
                    yield ev
                return

            assistant_msg = Message(conversation_id=conv_id, role="assistant",
                                    content=answer,
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
