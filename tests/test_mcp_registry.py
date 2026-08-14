"""MCP 注册表测试 - 注册/发现/调用/参数校验, 纯 Python 无 I/O"""
import pytest

from backend.mcp.registry import Tool, ToolNotFoundError, ToolParamError, ToolRegistry


@pytest.fixture()
def fresh_registry():
    return ToolRegistry()


async def _echo(arguments: dict) -> dict:
    return {"echo": arguments}


ECHO_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def test_register_and_list_tools(fresh_registry):
    fresh_registry.register(Tool(name="echo", description="回显工具", input_schema=ECHO_SCHEMA, handler=_echo))
    tools = fresh_registry.list_tools()
    assert [t.name for t in tools] == ["echo"]
    assert tools[0].description == "回显工具"
    assert tools[0].input_schema["required"] == ["text"]


def test_duplicate_name_raises(fresh_registry):
    fresh_registry.register(Tool("echo", "回显", ECHO_SCHEMA, _echo))
    with pytest.raises(ValueError, match="已注册"):
        fresh_registry.register(Tool("echo", "重复", ECHO_SCHEMA, _echo))


@pytest.mark.asyncio
async def test_call_success(fresh_registry):
    fresh_registry.register(Tool("echo", "回显", ECHO_SCHEMA, _echo))
    result = await fresh_registry.call("echo", {"text": "hi"})
    assert result == {"echo": {"text": "hi"}}


@pytest.mark.asyncio
async def test_call_unknown_tool(fresh_registry):
    with pytest.raises(ToolNotFoundError, match="未知工具"):
        await fresh_registry.call("nope", {})


@pytest.mark.asyncio
async def test_call_missing_required_param(fresh_registry):
    fresh_registry.register(Tool("echo", "回显", ECHO_SCHEMA, _echo))
    with pytest.raises(ToolParamError, match="缺少必填参数: text"):
        await fresh_registry.call("echo", {})


@pytest.mark.asyncio
async def test_call_wrong_type_param(fresh_registry):
    fresh_registry.register(Tool("echo", "回显", ECHO_SCHEMA, _echo))
    with pytest.raises(ToolParamError, match="应为 string"):
        await fresh_registry.call("echo", {"text": 123})
