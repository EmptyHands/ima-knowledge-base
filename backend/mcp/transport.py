"""MCP 传输层 - SSE over FastAPI: 会话管理 + 共享密钥鉴权 + 消息路由"""
import asyncio
import json
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from backend.core.config import get_config
from backend.mcp import protocol
from backend.mcp.registry import registry

router = APIRouter(tags=["mcp"])

_sessions: dict[str, asyncio.Queue] = {}


def _require_mcp_key(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """共享密钥鉴权; 未配置 MCP_API_KEY 时 MCP 端点整体禁用(404)"""
    expected = (get_config().mcp_api_key or "").strip()
    if not expected:
        raise HTTPException(status_code=404, detail="MCP 未启用(未配置 MCP_API_KEY)")
    provided = ""
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided:
        provided = request.query_params.get("api_key", "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="无效的 MCP API 密钥")


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@router.get("/mcp/sse")
async def sse(request: Request, _: None = Depends(_require_mcp_key)):
    session_id = uuid.uuid4().hex
    queue: asyncio.Queue = asyncio.Queue()
    _sessions[session_id] = queue
    endpoint_path = f"/mcp/messages?session_id={session_id}"

    async def event_stream():
        try:
            yield _sse("endpoint", endpoint_path)
            while True:
                message = await queue.get()
                yield _sse("message", json.dumps(message, ensure_ascii=False))
        finally:
            _sessions.pop(session_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/mcp/messages")
async def messages(request: Request, session_id: str, _: None = Depends(_require_mcp_key)):
    queue = _sessions.get(session_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="未知会话")
    raw = (await request.body()).decode("utf-8")
    response = await protocol.handle_request(protocol.parse_message(raw), registry)
    if response is not None:
        await queue.put(response)
    return Response(status_code=200, content="")
