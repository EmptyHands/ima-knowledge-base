# DEV-013 MCP 工具注册发现系统 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 手写轻量 MCP 服务器(JSON-RPC 2.0 子集 + SSE over FastAPI),把现有 web_search / vector_search / kb_status 三个工具通过注册表暴露为 MCP 工具,并重构 retriever_agent 内部走注册表调用。

**Architecture:** 四层分离 `backend/mcp/`:registry(工具注册/发现/参数校验,纯 Python)→ protocol(JSON-RPC 编解码 + MCP 方法分发,纯函数)→ transport(SSE 端点 + 共享密钥鉴权 + 会话管理)→ tools(三个工具,复用 `backend/core/retrieval.py`)。外部客户端经 `GET /mcp/sse` + `POST /mcp/messages` 走 JSON-RPC;内部 agent 进程内直调 `registry.call`,不走 HTTP 回环。

**Tech Stack:** Python 3.10+ / FastAPI / SSE / JSON-RPC 2.0 / pytest-asyncio。零新增依赖(不引入 mcp SDK)。

**测试命令:** `venv/Scripts/python.exe -m pytest tests/<file>.py -v`(单文件)、`venv/Scripts/python.exe -m pytest tests/ -v`(全套)。所有测试离线,不烧 API、不联网。

---

## Task 1: registry.py — 工具注册表

**Files:**
- Create: `backend/mcp/__init__.py`
- Create: `backend/mcp/registry.py`
- Test: `tests/test_mcp_registry.py`

**Step 1: Write the failing test**

Create `tests/test_mcp_registry.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_mcp_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.mcp.registry'`

**Step 3: Write minimal implementation**

Create `backend/mcp/registry.py`:

```python
"""工具注册表 - MCP 工具注册/发现/调用, 纯 Python 无 I/O"""
from dataclasses import dataclass
from typing import Awaitable, Callable


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
        result = await tool.handler(arguments)
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
```

Create `backend/mcp/__init__.py`(保证任何 `backend.mcp.*` 导入都会注册内置工具):

```python
"""MCP 层 - 工具注册表 + 协议 + SSE 传输"""
from backend.mcp import tools  # noqa: F401  导入即注册内置工具
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_mcp_registry.py -v`
Expected: 6 passed

> 注意:此时代码 `from backend.mcp import tools` 会失败(文件还不存在),属预期 —— 先创建 `__init__.py` 但暂不执行其中的 tools 导入测试;若 pytest 收集时报错,先创建空的 `backend/mcp/tools.py` 占位,Task 3 再填充实现。

**Step 5: Commit**

```bash
git add backend/mcp/__init__.py backend/mcp/registry.py backend/mcp/tools.py tests/test_mcp_registry.py
git commit -m "feat: MCP 工具注册表 (registry) - 注册/发现/参数校验"
```

---

## Task 2: protocol.py — MCP 协议层(纯函数)

**Files:**
- Create: `backend/mcp/protocol.py`
- Test: `tests/test_mcp_protocol.py`

**Step 1: Write the failing test**

Create `tests/test_mcp_protocol.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_mcp_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.mcp.protocol'`

**Step 3: Write minimal implementation**

Create `backend/mcp/protocol.py`:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_mcp_protocol.py -v`
Expected: 11 passed

**Step 5: Commit**

```bash
git add backend/mcp/protocol.py tests/test_mcp_protocol.py
git commit -m "feat: MCP 协议层 - JSON-RPC 2.0 子集分发 (initialize/ping/tools/list/tools/call)"
```

---

## Task 3: tools.py — 三个内置工具

**Files:**
- Create(替换占位): `backend/mcp/tools.py`
- Test: `tests/test_mcp_tools.py`

**Step 1: Write the failing test**

Create `tests/test_mcp_tools.py`:

```python
"""MCP 内置工具测试 - monkeypatch 底层检索 + 临时 SQLite"""
import pytest

from backend.mcp.registry import ToolError, registry


@pytest.mark.asyncio
async def test_web_search_tool(monkeypatch):
    from backend.core import retrieval
    calls = {}

    async def fake_web_search(query, max_results=5):
        calls["query"] = query
        calls["max_results"] = max_results
        return [{"title": "T", "url": "https://a.com", "snippet": "s"}]

    monkeypatch.setattr(retrieval, "web_search", fake_web_search)
    result = await registry.call("web_search", {"query": "最新动态", "max_results": 3})
    assert calls == {"query": "最新动态", "max_results": 3}
    assert result["results"][0]["url"] == "https://a.com"


@pytest.mark.asyncio
async def test_web_search_default_max_results(monkeypatch):
    from backend.core import retrieval
    seen = {}

    async def fake_web_search(query, max_results=5):
        seen["max_results"] = max_results
        return []

    monkeypatch.setattr(retrieval, "web_search", fake_web_search)
    await registry.call("web_search", {"query": "q"})
    assert seen["max_results"] == 5


class FakeStore:
    def __init__(self, results):
        self._results = results

    async def search(self, kb_id, query, top_k=5):
        return self._results[:top_k]


@pytest.mark.asyncio
async def test_vector_search_tool(app_client, monkeypatch):
    from backend.core import retrieval
    from backend.core.database import get_db_session
    from backend.models.database import Document
    db = get_db_session()
    db.add(Document(id="doc1", kb_id="kb1", filename="t.pdf", file_path="/tmp/t.pdf"))
    db.commit()
    db.close()

    monkeypatch.setattr(retrieval, "get_vector_store", lambda: FakeStore([
        {"score": 0.81, "text": "Transformer 使用自注意力", "doc_id": "doc1", "page": 3, "chunk_index": 0},
    ]))
    result = await registry.call("vector_search", {"kb_id": "kb1", "question": "Transformer 是什么", "top_k": 5})
    assert result["chunks"][0]["doc_name"] == "t.pdf"
    assert result["chunks"][0]["search_type"] == "dense"


@pytest.mark.asyncio
async def test_kb_status_tool(app_client):
    from backend.core.database import get_db_session
    from backend.models.database import Document, KnowledgeBase
    db = get_db_session()
    db.add(KnowledgeBase(id="kb-1", user_id="u1", name="测试库"))
    db.add_all([
        Document(id="d1", kb_id="kb-1", filename="a.pdf", file_path="/tmp/a.pdf",
                 status="ready", chunk_count=10),
        Document(id="d2", kb_id="kb-1", filename="b.pdf", file_path="/tmp/b.pdf",
                 status="processing", chunk_count=0),
    ])
    db.commit()
    db.close()

    result = await registry.call("kb_status", {"kb_id": "kb-1"})
    assert result == {"kb_id": "kb-1", "name": "测试库", "document_count": 2,
                      "ready_count": 1, "chunk_count": 10}


@pytest.mark.asyncio
async def test_kb_status_missing_kb(app_client):
    with pytest.raises(ToolError, match="知识库不存在"):
        await registry.call("kb_status", {"kb_id": "nope"})
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -v`
Expected: FAIL — 工具未注册(`未知工具: web_search` 或 `AttributeError`)

**Step 3: Write minimal implementation**

Replace(或填充占位)`backend/mcp/tools.py`:

```python
"""MCP 内置工具 - 封装现有检索/搜索能力, 复用 backend/core/retrieval.py"""
from backend.core import retrieval
from backend.core.database import get_db_session
from backend.models.database import Document, KnowledgeBase
from backend.mcp.registry import ToolError, tool


@tool(
    name="web_search",
    description="联网搜索(Tavily): 获取最新网络信息, 返回标题/URL/摘要列表",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "max_results": {"type": "integer", "description": "返回条数, 默认 5"},
        },
        "required": ["query"],
    },
)
async def web_search(arguments: dict) -> dict:
    results = await retrieval.web_search(arguments["query"], arguments.get("max_results", 5))
    return {"results": results}


@tool(
    name="vector_search",
    description="知识库语义检索(三级降级: 向量→关键词→空), 返回带文档名/页码的片段",
    input_schema={
        "type": "object",
        "properties": {
            "kb_id": {"type": "string", "description": "知识库 ID"},
            "question": {"type": "string", "description": "查询问题"},
            "top_k": {"type": "integer", "description": "返回条数, 默认 5"},
        },
        "required": ["kb_id", "question"],
    },
)
async def vector_search(arguments: dict) -> dict:
    chunks = await retrieval.vector_search(arguments["kb_id"], arguments["question"],
                                           arguments.get("top_k", 5))
    return {"chunks": chunks}


@tool(
    name="kb_status",
    description="查询知识库状态: 文档数/就绪数/总块数",
    input_schema={
        "type": "object",
        "properties": {"kb_id": {"type": "string", "description": "知识库 ID"}},
        "required": ["kb_id"],
    },
)
async def kb_status(arguments: dict) -> dict:
    db = get_db_session()
    try:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == arguments["kb_id"]).first()
        if kb is None:
            raise ToolError(f"知识库不存在: {arguments['kb_id']}")
        docs = db.query(Document).filter(Document.kb_id == kb.id).all()
        return {
            "kb_id": kb.id,
            "name": kb.name,
            "document_count": len(docs),
            "ready_count": sum(1 for d in docs if d.status == "ready"),
            "chunk_count": sum(d.chunk_count or 0 for d in docs),
        }
    finally:
        db.close()
```

> 关键实现约定:tools.py 用 `from backend.core import retrieval` 后以 `retrieval.web_search(...)` 调用,而不是 `from backend.core.retrieval import web_search` —— 这样测试 monkeypatch `retrieval.web_search` 才生效(属性在调用时解析)。

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add backend/mcp/tools.py tests/test_mcp_tools.py
git commit -m "feat: MCP 内置工具 - web_search/vector_search/kb_status"
```

---

## Task 4: transport.py — SSE 传输层 + 配置挂载

**Files:**
- Create: `backend/mcp/transport.py`
- Modify: `backend/core/config.py`(AppConfig 增加 `mcp_api_key`)
- Modify: `backend/main.py`(挂载 MCP router)
- Modify: `.env.example`(增加 MCP_API_KEY 说明)
- Test: `tests/test_mcp_transport.py`

**Step 1: Write the failing test**

Create `tests/test_mcp_transport.py`:

```python
"""MCP SSE 传输层测试 - 鉴权/会话/完整握手往返"""
import json
import threading
import time
from queue import Empty, Queue

import pytest

TEST_KEY = "test-secret"


def _make_client(tmp_path, monkeypatch, with_key: bool):
    """构造测试客户端: 独立临时 DB + (可选) MCP_API_KEY"""
    if with_key:
        monkeypatch.setenv("MCP_API_KEY", TEST_KEY)
    else:
        monkeypatch.delenv("MCP_API_KEY", raising=False)
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import backend.core.config as config_module
    import backend.core.database as database_module
    config_module._config = None
    database_module.engine = None
    database_module.SessionLocal = None
    from backend.core.database import init_database, get_db_session
    from backend.main import app
    from fastapi.testclient import TestClient
    from backend.models.database import Base
    init_database()
    session = get_db_session()
    Base.metadata.drop_all(session.get_bind())
    Base.metadata.create_all(session.get_bind())
    session.close()
    return TestClient(app)


@pytest.fixture()
def mcp_app_client(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch, with_key=True) as client:
        yield client


@pytest.fixture()
def mcp_disabled_client(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch, with_key=False) as client:
        yield client


def _wait_for(queue: Queue, prefix: str, timeout: float = 5.0) -> str:
    """从行队列中取到以 prefix 开头的行(跳过其他行)"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            line = queue.get(timeout=0.1)
        except Empty:
            continue
        if line.startswith(prefix):
            return line
    raise AssertionError(f"超时未读到 {prefix!r} 开头的行")


def test_sse_requires_key(mcp_app_client):
    assert mcp_app_client.get("/mcp/sse").status_code == 401
    assert mcp_app_client.get("/mcp/sse", params={"api_key": "wrong"}).status_code == 401
    assert mcp_app_client.post("/mcp/messages?session_id=abc").status_code == 401


def test_mcp_disabled_without_key(mcp_disabled_client):
    assert mcp_disabled_client.get("/mcp/sse").status_code == 404
    assert mcp_disabled_client.post("/mcp/messages?session_id=abc").status_code == 404


def test_sse_emits_endpoint_event_and_cleans_up(mcp_app_client):
    with mcp_app_client.stream("GET", "/mcp/sse", params={"api_key": TEST_KEY}) as resp:
        assert resp.status_code == 200
        it = resp.iter_lines()
        data_line = None
        for line in it:
            if line and line.startswith("data: /mcp/messages?session_id="):
                data_line = line
                break
        assert data_line is not None
        session_id = data_line.split("session_id=")[1].strip()
        r = mcp_app_client.post(f"/mcp/messages?session_id={session_id}",
                                json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 200
        assert session_id in __import__("backend.mcp.transport", fromlist=["_sessions"])._sessions
    # 连接关闭后会话应被清理
    from backend.mcp import transport
    deadline = time.time() + 3
    while session_id in transport._sessions and time.time() < deadline:
        time.sleep(0.05)
    assert session_id not in transport._sessions


def test_post_unknown_session_404(mcp_app_client):
    resp = mcp_app_client.post("/mcp/messages?session_id=does-not-exist",
                               json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert resp.status_code == 404


def test_full_handshake_roundtrip(mcp_app_client):
    """完整握手: initialize → tools/list → tools/call, 响应经 SSE message 事件返回"""
    lines_queue = Queue()

    def consume():
        with mcp_app_client.stream("GET", "/mcp/sse", params={"api_key": TEST_KEY}) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line:
                    lines_queue.put(line)

    t = threading.Thread(target=consume, daemon=True)
    t.start()

    endpoint_data = _wait_for(lines_queue, "data: /mcp/messages?session_id=")
    session_id = endpoint_data.split("session_id=")[1].strip()

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "kb_status", "arguments": {"kb_id": "missing"}}},
    ]
    for req in requests:
        resp = mcp_app_client.post(f"/mcp/messages?session_id={session_id}", json=req)
        assert resp.status_code == 200

    messages = []
    for _ in range(3):
        _wait_for(lines_queue, "event: message")
        data_line = _wait_for(lines_queue, "data: {")
        messages.append(json.loads(data_line[len("data: "):]))

    by_id = {m["id"]: m for m in messages}
    assert by_id[1]["result"]["protocolVersion"].startswith("2025-")
    assert any(t["name"] == "vector_search" for t in by_id[2]["result"]["tools"])
    assert by_id[3]["result"]["isError"] is True
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_mcp_transport.py -v`
Expected: FAIL — `404 Not Found`(router 未挂载)

**Step 3: Write minimal implementation**

Create `backend/mcp/transport.py`:

```python
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
```

Modify `backend/core/config.py`:
- 在 `AppConfig` 字段区(JWT 配置附近)加一行:`mcp_api_key: str = ""`
- 在 `__post_init__` 中(JWT 行之后)加一行:`self.mcp_api_key = os.getenv("MCP_API_KEY", "").strip()`

Modify `backend/main.py`:
- 第 13 行后加:`from backend.mcp.transport import router as mcp_router  # noqa: E402`
- 第 53 行(`app.include_router(chat.router)`)后加:`app.include_router(mcp_router)`

Modify `.env.example`,末尾追加:

```
# --- MCP 工具服务器 (可选, 未配置则 MCP 端点禁用) ---
# 外部 MCP 客户端(如 MCP Inspector)连接 /mcp/sse 的共享密钥
MCP_API_KEY=
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_mcp_transport.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add backend/mcp/transport.py backend/core/config.py backend/main.py .env.example tests/test_mcp_transport.py
git commit -m "feat: MCP SSE 传输层 - 会话管理/共享密钥鉴权/消息路由"
```

---

## Task 5: retriever_agent 内部重构走注册表

**Files:**
- Modify: `backend/agents/retriever_agent.py`(整体重写为注册表调用)
- Modify: `tests/test_retrieval.py`(两处 monkeypatch 目标从 `retriever_module.web_search` 改为 `retrieval_module.web_search`)
- Test: `tests/test_retrieval.py`、`tests/test_chat_stream.py`

**Step 1: Write the failing test(先改断言方向)**

`tests/test_retrieval.py` 两处改动(第 123 行、第 143 行):

```python
# 改动前
monkeypatch.setattr(retriever_module, "web_search", fake_web_search)
# 改动后
monkeypatch.setattr(retrieval_module, "web_search", fake_web_search)
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_retrieval.py -v`
Expected: FAIL — 改动后的 monkeypatch 目标在旧代码中不存在(`AttributeError: module 'backend.core.retrieval' has no attribute ...` 不存在,而是旧 retriever_module.web_search 场景);重构后重跑失败原因是 `AttributeError: module 'backend.agents.retriever_agent' has no attribute 'web_search'`(若先实现)。

**Step 3: Rewrite minimal implementation**

Replace `backend/agents/retriever_agent.py` 全文:

```python
"""RetrieverAgent - 检索智能体: 三级降级检索 + 意图识别网络搜索(经 MCP 注册表调用工具)"""
from backend.core.retrieval import detect_web_intent
from backend.mcp.registry import registry


async def retrieve(question: str, kb_id: str, top_k: int = 5, force_web: bool = False) -> dict:
    """检索入口, 返回 {"chunks": [...], "web_results": [...]}

    force_web=True 时无条件触发网络搜索(反问确认后的重检索)
    """
    chunks = (await registry.call("vector_search", {"kb_id": kb_id, "question": question, "top_k": top_k}))["chunks"]
    web_results = []
    if force_web or detect_web_intent(question):
        web_results = (await registry.call("web_search", {"query": question}))["results"]
    return {"chunks": chunks, "web_results": web_results}
```

> 说明:retriever_agent 导入 `backend.mcp.registry` 会触发 `backend/mcp/__init__.py` 执行,内置工具自动注册,无需显式 import tools。

**Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_retrieval.py tests/test_chat_stream.py tests/test_fallback.py -v`
Expected: 全部通过(注册表调用链: retriever → registry.call → tools handler → retrieval.vector_search/web_search,monkeypatch 目标 `retrieval_module.*` 在调用时解析,仍然生效)

**Step 5: Commit**

```bash
git add backend/agents/retriever_agent.py tests/test_retrieval.py
git commit -m "refactor: retriever_agent 改走 MCP 注册表调用工具"
```

---

## Task 6: 文档与全套回归

**Files:**
- Modify: `README.md`(功能列表、架构图、.env 说明、MCP 连接示例、版本变更记录)
- Modify: `DEV_LOG.md`(DEV-013 标记 ✅)
- Test: 全套 `tests/`

**Step 1: README 更新**

1. **功能列表** 增加一条:
   ```markdown
   - **MCP 工具服务器**: 手写轻量 MCP(JSON-RPC 2.0 + SSE),联网搜索/知识库检索/知识库状态封装为 MCP 工具,支持外部客户端(MCP Inspector 等)注册发现与调用
   ```
2. **架构 mermaid**: `RET` 节点下加 `MCP["MCP Server: SSE /mcp/sse"]`,连线 `RET --> MCP` 与 `MCP --> WEB`(保持现有节点命名风格,label 特殊字符用双引号)。
3. **技术选型理由** 表加一行:`手写轻量 MCP 协议层 | mcp SDK | JSON-RPC 子集 200 行可讲可测,协议层纯函数离线单测,契合「手写不重框架」风格;后续可平滑换 stdio 传输接 Claude Desktop`
4. **.env 说明**(快速开始后的配置提示)与 **MCP 连接示例** 新章节:
   ```markdown
   ## MCP 工具调用

   配置 `MCP_API_KEY` 后(未配置则 MCP 端点禁用),外部 MCP 客户端可连接:

   - MCP Inspector:URL `http://localhost:8000/mcp/sse`,Headers `Authorization: Bearer <MCP_API_KEY>`
   - 也可直接 POST JSON-RPC:`curl -X POST "http://localhost:8000/mcp/messages?session_id=<sid>&api_key=<key>" ...`

   已注册工具:`web_search`(Tavily 联网搜索)、`vector_search`(知识库三级降级检索)、`kb_status`(知识库状态)。新增工具只需在 `backend/mcp/tools.py` 用 `@tool` 装饰器注册。
   ```
5. **测试数**:83 → 按实际新增数更新(预计 ~109)。
6. **版本变更记录** 顶部加一行:
   ```markdown
   | v1.1.0 | 2026-08-14 | 新增 DEV-013:手写轻量 MCP 工具注册发现系统(registry/protocol/transport/tools 四层,SSE 传输 + 共享密钥鉴权,web_search/vector_search/kb_status 三工具,retriever 内部改走注册表) |
   ```

**Step 2: DEV_LOG.md 更新**

将 DEV-013 条目改为:

```markdown
## ✅ DEV-013 — 缺少 MCP 外部工具协议扩展

- **提出版本**:v1.0.7
- **提出日期**:2026-08-13
- **状态**:✅ 已解决
- **解决版本**:v1.1.0
- **解决时间**:2026-08-14
- **根因**:工具全部硬编码为函数调用,无工具注册表/自描述/协议层,外部无法发现与调用。
- **解决方案**:新增 `backend/mcp/` 四层 —— registry(工具注册/发现/参数校验,`@tool` 装饰器 + 模块级单例)、protocol(JSON-RPC 2.0 子集 initialize/ping/tools/list/tools/call,纯函数)、transport(SSE over FastAPI,`GET /mcp/sse` + `POST /mcp/messages`,内存会话表 + 共享密钥鉴权,未配置 `MCP_API_KEY` 端点 404 禁用)、tools(web_search/vector_search/kb_status 复用 retrieval.py)。`main.py` 挂载 router;retriever_agent 改为经注册表调用工具(进程内直调无 HTTP 回环),返回结构不变。新增 4 个测试文件(registry/protocol/transport/tools)约 26 个用例,全套回归绿。
- **启发**:注册表 + 纯函数协议层把「工具协议化」拆成了两个可独立测试的扩展点 —— 加工具只动 tools.py,加传输(如 stdio 接 Claude Desktop)只动 transport 层;内部调用走注册表而非直调函数,让「工具」有了统一的参数校验与自描述,是 DEV-012 langgraph 重构的协议底座。工具层用 `from backend.core import retrieval` + 调用时属性解析,monkeypatch 才能生效,这是手写工具层与测试友好之间的关键约定。
```

「未解决条目速览」表中 DEV-013 行从 ⚠️ 改 ✅。

**Step 3: 全套回归**

Run: `venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全部通过(83 + 新增 ≈ 109)

> 注意:若出现失败,先确认是否集中在 `answer_agent.py / citation_agent.py / ChatArea.tsx / CitationCard.tsx / test_chat_stream.py / test_citation.py` —— 这些是 DEV-018 未提交的进行中改动(与本任务无关)。本任务相关失败只可能出现在 retriever_agent / test_retrieval / mcp 相关文件;若 DEV-018 改动造成全绿基线破坏,先与用户确认如何处理,不要擅自改 DEV-018 代码。

**Step 4: Commit**

```bash
git add README.md DEV_LOG.md
git commit -m "docs: DEV-013 README/DDEV_LOG 记录 (v1.1.0)"
```

---

## 验收清单

1. `venv/Scripts/python.exe -m pytest tests/ -v` 全绿(含新增 ~26 个 MCP 用例)
2. MCP Inspector 可连接 `http://localhost:8000/mcp/sse`(带 `Authorization: Bearer <MCP_API_KEY>`),`tools/list` 显示三个工具,`tools/call` 可调用 `kb_status`/`web_search`
3. 未配置 `MCP_API_KEY` 时 `/mcp/sse` 返回 404,系统其他功能不受影响
4. retriever_agent 返回结构 `{"chunks": [...], "web_results": [...]}` 不变,chat 流式问答行为无变化
