"""会话与消息路由 - SSE 流式问答 (langgraph 管线: 检索/判定/人机交互/回答)"""
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import backend.graph.qa_graph as qa_graph
from backend.api.routes.auth import get_current_user
from backend.core.database import get_db
from backend.graph.qa_graph import HISTORY_LIMIT, checkpointer, graph
from backend.models.database import Conversation, Document, KnowledgeBase, Message, User
from backend.models.messages import ChatMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/conversations", tags=["会话"])

CONFIRM_WORDS = ("需要", "要", "好", "是", "可以", "联网", "搜索", "用")
_RE_FALLBACK_QUESTION = re.compile(r"未找到与『(.+?)』相关的内容")


def _confirm_question(history: list[ChatMessage], question: str) -> tuple[str, bool]:
    """反问确认识别: 最近助手消息是反问模板且本次回复为确认词时, 返回(原问题, True)"""
    q = question.strip().strip("。.!！?？ ")
    last_assistant = next((m for m in reversed(history) if m.role == "assistant"), None)
    if last_assistant:
        m = _RE_FALLBACK_QUESTION.search(last_assistant.content or "")
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
    """SSE 流式问答: status → chunk* → citations → done / error (PRD §6.2)

    编排委托 langgraph 图(qa_graph): 无可靠结果 → ask_user interrupt 挂起 →
    用户确认后 Command(resume=True) 回到检索节点强制联网重跑。
    """
    conv = _get_owned_conv(db, conv_id, user)
    _check_kb_owned(db, conv.kb_id, user)
    question = req.question.strip()

    history_rows = db.query(Message).filter(Message.conversation_id == conv_id) \
        .order_by(Message.created_at.asc()).all()
    history = [ChatMessage(role=m.role, content=m.content) for m in history_rows[-HISTORY_LIMIT:]]

    doc_count = db.query(Document).filter(Document.kb_id == conv.kb_id).count()
    question, is_confirm = _confirm_question(history, question)

    user_msg = Message(conversation_id=conv_id, role="user", content=req.question.strip())
    db.add(user_msg)
    db.commit()

    def _initial_state(allow_web: bool = False) -> dict:
        return {"question": question, "kb_id": conv.kb_id, "conv_id": conv.id,
                "kb_empty": doc_count == 0,
                "history": [{"role": m.role, "content": m.content} for m in history],
                "allow_web_search": allow_web}

    def _persist_assistant(content: str, citations=None) -> Message:
        assistant_msg = Message(conversation_id=conv_id, role="assistant",
                                content=content, citations_json=citations or None)
        db.add(assistant_msg)
        if conv.title == "新对话":
            conv.title = question[:20]
        db.commit()
        return assistant_msg

    async def _drive_graph(graph_input, config: dict):
        """驱动图并映射 SSE 事件; 流结束后按 中断反问/终止文案/正常回答 三分支收尾"""
        interrupted = False
        saw_status = False
        citations = []
        answer_parts = []
        async for mode, payload in graph.astream(graph_input, config,
                                                 stream_mode=["updates", "custom"]):
            if mode == "custom":
                if payload["type"] == "status":
                    saw_status = True
                    yield _sse("status", {"text": payload["data"]})
                elif payload["type"] == "chunk":
                    answer_parts.append(payload["data"])
                    yield _sse("chunk", {"text": payload["data"]})
                elif payload["type"] == "citations":
                    citations = payload["data"]
            elif isinstance(payload, dict) and "__interrupt__" in payload:
                interrupted = True
                interrupt_text = payload["__interrupt__"][0].value["text"]
        if interrupted:
            # 反问: status 已由 ask_user 的 custom 流下发, 文案以 chunk 下发
            # (前端仅累积 chunk, 无 chunk 不渲染) + 入库 + 空引用 + done
            msg = _persist_assistant(interrupt_text)
            yield _sse("chunk", {"text": interrupt_text})
            yield _sse("citations", {"items": []})
            yield _sse("done", {"message_id": msg.id})
        elif not answer_parts:
            # 终止分支(已联网仍无可靠结果 / 已联网仍空回答): 图内无 chunk,
            # 文案从 final state 的 fallback_text 取; 仅当本次 run 无任何
            # custom status 时才自补 status(resume 会重跑 ask_user 再发一次)
            state = await graph.aget_state(config)
            text = state.values.get("fallback_text")
            if text == qa_graph.WEB_UNAVAILABLE:
                status_text = "知识库中未检索到相关内容"
            elif text == qa_graph.NO_ANSWER_TERMINAL:
                status_text = "未能生成有效回答"
            else:
                raise RuntimeError(f"图终止但无有效 fallback_text: {text!r}")
            if not saw_status:
                yield _sse("status", {"text": status_text})
            msg = _persist_assistant(text)
            yield _sse("chunk", {"text": text})
            yield _sse("citations", {"items": []})
            yield _sse("done", {"message_id": msg.id})
        else:
            answer = "".join(answer_parts).strip()
            msg = _persist_assistant(answer, citations)
            yield _sse("citations", {"items": citations})
            yield _sse("done", {"message_id": msg.id})

    async def _discard_thread(config: dict):
        try:
            await checkpointer.adelete_thread(config["configurable"]["thread_id"])
        except Exception:
            pass

    async def gen():
        try:
            config = {"configurable": {"thread_id": conv_id}}
            try:
                if is_confirm:
                    async for ev in _drive_graph(Command(resume=True), config):
                        yield ev
                else:
                    await _discard_thread(config)
                    async for ev in _drive_graph(_initial_state(), config):
                        yield ev
            except (KeyError, ValueError):
                # 线程丢失(进程重启/无中断可恢复): 降级为带联网的新 run
                await _discard_thread(config)
                async for ev in _drive_graph(_initial_state(allow_web=True), config):
                    yield ev
        except Exception as e:
            logger.exception("问答管线失败")
            yield _sse("error", {"text": f"生成失败: {str(e)[:200]}"})

    return StreamingResponse(gen(), media_type="text/event-stream")
