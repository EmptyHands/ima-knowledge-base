"""MCP 协议层 - JSON-RPC 2.0 子集 (initialize/ping/tools/list/tools/call), 纯函数无 I/O"""
import json

from backend.mcp.registry import ToolNotFoundError, ToolParamError, registry as _default_registry

SERVER_NAME = "ima-knowledge-base"
SERVER_VERSION = "1.1.0"
PROTOCOL_VERSION = "2025-03-26"


def parse_message(raw: str) -> dict | None:
    """解析 JSON-RPC 请求文本, 非法 JSON/非对象返回 None"""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return msg if isinstance(msg, dict) else None


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


async def handle_request(msg: dict | None, reg=None) -> dict | None:
    """分发 MCP 方法请求, 返回响应 dict; 通知返回 None"""
    reg = reg or _default_registry
    if msg is None:
        return _error(None, -32700, "Parse error")
    if msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _error(None, -32600, "Invalid request")
    req_id = msg.get("id")
    method = msg["method"]

    if req_id is None:
        return None  # 通知: 静默忽略

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in reg.list_tools()
        ]})
    if method == "tools/call":
        params = msg.get("params") or {}
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(req_id, -32602, "arguments 应为对象")
        try:
            result = await reg.call(params.get("name"), arguments)
        except (ToolNotFoundError, ToolParamError) as e:
            return _error(req_id, -32602, str(e))
        except Exception as e:
            return _result(req_id, {"content": [{"type": "text", "text": f"工具执行失败: {e}"}], "isError": True})
        return _result(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
    return _error(req_id, -32601, f"Method not found: {method}")
