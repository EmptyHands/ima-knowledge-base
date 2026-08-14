"""MCP SSE 传输层测试 - 鉴权/会话/完整握手往返

TestClient 无法测试无限长连接流(Starlette 1.4 的 TestClient 会等 app 完成后才返回),
因此流式往返测试改用真实 uvicorn 服务器 + httpx 流式客户端。
"""
import json
import socket
import threading
import time

import httpx
import pytest

TEST_KEY = "test-secret"


def _env_setup(tmp_path, monkeypatch, with_key: bool):
    """独立临时 DB + (可选) MCP_API_KEY, 并重置配置/数据库单例"""
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


def _make_client(tmp_path, monkeypatch, with_key: bool):
    """构造 TestClient: 供非流式(鉴权/禁用/未知会话)测试使用"""
    _env_setup(tmp_path, monkeypatch, with_key)
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


@pytest.fixture()
def mcp_server(tmp_path, monkeypatch):
    """真实 uvicorn 服务器 - 长连接 SSE 流式往返测试专用"""
    _env_setup(tmp_path, monkeypatch, with_key=True)
    from backend.main import app
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("uvicorn 未在 15s 内就绪")
    yield base_url
    server.should_exit = True
    thread.join(timeout=5)


def test_sse_requires_key(mcp_app_client):
    assert mcp_app_client.get("/mcp/sse").status_code == 401
    assert mcp_app_client.get("/mcp/sse", params={"api_key": "wrong"}).status_code == 401
    assert mcp_app_client.post("/mcp/messages?session_id=abc").status_code == 401


def test_mcp_disabled_without_key(mcp_disabled_client):
    assert mcp_disabled_client.get("/mcp/sse").status_code == 404
    assert mcp_disabled_client.post("/mcp/messages?session_id=abc").status_code == 404


def test_sse_emits_endpoint_event_and_cleans_up(mcp_server):
    from backend.mcp import transport

    with httpx.stream("GET", f"{mcp_server}/mcp/sse",
                      params={"api_key": TEST_KEY}, timeout=10) as resp:
        assert resp.status_code == 200
        it = resp.iter_lines()
        session_id = None
        for line in it:
            if line.startswith("data: /mcp/messages?session_id="):
                session_id = line.split("session_id=")[1].strip()
                break
        assert session_id is not None
        r = httpx.post(f"{mcp_server}/mcp/messages",
                       params={"session_id": session_id, "api_key": TEST_KEY},
                       json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 200
        assert session_id in transport._sessions
    # 连接关闭后会话应被清理
    deadline = time.time() + 3
    while session_id in transport._sessions and time.time() < deadline:
        time.sleep(0.05)
    assert session_id not in transport._sessions


def test_post_unknown_session_404(mcp_app_client):
    resp = mcp_app_client.post("/mcp/messages",
                               params={"session_id": "does-not-exist", "api_key": TEST_KEY},
                               json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert resp.status_code == 404


def test_full_handshake_roundtrip(mcp_server):
    """完整握手: initialize → tools/list → tools/call, 响应经 SSE message 事件返回"""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "kb_status", "arguments": {"kb_id": "missing"}}},
    ]
    with httpx.stream("GET", f"{mcp_server}/mcp/sse",
                      params={"api_key": TEST_KEY}, timeout=10) as resp:
        assert resp.status_code == 200
        it = resp.iter_lines()
        for line in it:
            if line.startswith("data: /mcp/messages?session_id="):
                session_id = line.split("session_id=")[1].strip()
                break
        assert session_id is not None
        for req in requests:
            r = httpx.post(f"{mcp_server}/mcp/messages",
                           params={"session_id": session_id, "api_key": TEST_KEY}, json=req)
            assert r.status_code == 200

        messages = []
        for _ in range(3):
            for line in it:
                if line == "event: message":
                    break
            data_line = next(it)
            messages.append(json.loads(data_line[len("data: "):]))

    by_id = {m["id"]: m for m in messages}
    assert by_id[1]["result"]["protocolVersion"].startswith("2025-")
    assert any(t["name"] == "vector_search" for t in by_id[2]["result"]["tools"])
    assert by_id[3]["result"]["isError"] is True
