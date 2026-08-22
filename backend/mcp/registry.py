"""工具注册表 - MCP 工具注册/发现/调用, 纯 Python 无 I/O"""
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from backend.utils import detail_trace


class ToolError(Exception):
    """工具执行失败(协议层转为 isError 结果, 而非 JSON-RPC 错误)"""


class ToolParamError(ToolError):
    """工具参数校验失败(协议层转为 -32602)"""


class ToolNotFoundError(Exception):
    """工具不存在(协议层转为 -32602)"""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], Awaitable[dict]]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具已注册: {tool.name}")
        self._tools[tool.name] = tool

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    async def call(self, name: str, arguments: dict) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"未知工具: {name}")
        self._validate(arguments, tool.input_schema)
        t0 = time.perf_counter()
        result = await tool.handler(arguments)
        detail_trace.capture_tool(name, arguments, result or {},
                                  time.perf_counter() - t0)
        return result or {}

    @staticmethod
    def _validate(arguments: dict, schema: dict) -> None:
        for field_name in schema.get("required", []):
            if field_name not in arguments:
                raise ToolParamError(f"缺少必填参数: {field_name}")
        for field_name, value in arguments.items():
            expected = schema.get("properties", {}).get(field_name, {}).get("type")
            ok = {
                "string": isinstance(value, str),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "array": isinstance(value, list),
                "object": isinstance(value, dict),
            }.get(expected, True)
            if not ok:
                raise ToolParamError(f"参数 {field_name} 应为 {expected}")


registry = ToolRegistry()


def tool(name: str, description: str, input_schema: dict):
    """装饰器: 将 async 函数注册进全局注册表"""
    def decorator(fn):
        registry.register(Tool(name=name, description=description,
                                input_schema=input_schema, handler=fn))
        return fn
    return decorator
