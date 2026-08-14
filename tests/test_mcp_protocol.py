"""MCP 协议层测试 - 纯函数直测 JSON-RPC 语义, 无 I/O"""
import json

import pytest

from backend.mcp import protocol
from backend.mcp.registry import Tool, ToolRegistry


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()

    async def _echo(arguments: dict) -> dict:
        return {"echo": arguments}

    reg.register(Tool(name="echo", description="回显工具", input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }, handler=_echo))

    async def _boom(arguments: dict) -> dict:
        raise RuntimeError("工具爆炸")

    reg.register(Tool(name="boom", description="必炸工具",
                      input_schema={"type": "object", "properties": {}}, handler=_boom))
    return reg


@pytest.mark.asyncio
async def test_initialize_response():
    resp = await protocol.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {}},
    })
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == protocol.PROTOCOL_VERSION
    assert "tools" in resp["result"]["capabilities"]
    assert resp["result"]["serverInfo"]["name"]


@pytest.mark.asyncio
async def test_initialized_notification_no_response():
    resp = await protocol.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp is None


@pytest.mark.asyncio
async def test_ping():
    resp = await protocol.handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert resp == {"jsonrpc": "2.0", "id": 2, "result": {}}


@pytest.mark.asyncio
async def test_tools_list():
    reg = _make_registry()
    resp = await protocol.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, reg)
    tools = resp["result"]["tools"]
    assert [t["name"] for t in tools] == ["echo", "boom"]
    assert tools[0]["description"] == "回显工具"
    assert tools[0]["inputSchema"]["required"] == ["text"]


@pytest.mark.asyncio
async def test_tools_call_success():
    reg = _make_registry()
    resp = await protocol.handle_request({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "echo", "arguments": {"text": "hi"}},
    }, reg)
    assert json.loads(resp["result"]["content"][0]["text"]) == {"echo": {"text": "hi"}}


@pytest.mark.asyncio
async def test_tools_call_handler_exception_is_error_result():
    reg = _make_registry()
    resp = await protocol.handle_request({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "boom", "arguments": {}},
    }, reg)
    assert resp["result"]["isError"] is True


@pytest.mark.asyncio
async def test_tools_call_missing_param():
    reg = _make_registry()
    resp = await protocol.handle_request({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "echo", "arguments": {}},
    }, reg)
    assert resp["error"]["code"] == -32602
    assert "缺少必填参数" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_tools_call_unknown_tool():
    reg = _make_registry()
    resp = await protocol.handle_request({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "nope", "arguments": {}},
    }, reg)
    assert resp["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_bad_json_parse_error():
    resp = await protocol.handle_request(protocol.parse_message("{not json"))
    assert resp["error"]["code"] == -32700


@pytest.mark.asyncio
async def test_missing_jsonrpc_or_method():
    resp = await protocol.handle_request({"jsonrpc": "1.0", "id": 1, "method": "ping"})
    assert resp["error"]["code"] == -32600
    resp = await protocol.handle_request({"jsonrpc": "2.0", "id": 1})
    assert resp["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_unknown_method():
    resp = await protocol.handle_request({"jsonrpc": "2.0", "id": 1, "method": "bogus"})
    assert resp["error"]["code"] == -32601
