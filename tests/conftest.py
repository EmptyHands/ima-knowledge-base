"""pytest 共享 fixture - 每次测试用独立临时 SQLite 数据库"""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import backend.agents.retriever_agent as retriever_agent_module
import backend.core.config as config_module
import backend.core.database as database_module
import backend.core.llm_adapter as llm_adapter_module
from backend.models.database import Base


class FakeLLM:
    """测试用伪 LLM: 输出固定 token(含 [1] 引用标注), fail=True 模拟生成故障"""

    def __init__(self, tokens=None, fail=False):
        self._tokens = tokens or ["基于", "片段", "[1]", "的回答", "\n## 引用\n", "[1] 测试文档.pdf, 第1页"]
        self._fail = fail

    async def astream(self, prompt, system_prompt=None):
        if self._fail:
            raise RuntimeError("LLM 模拟故障")
        for token in self._tokens:
            yield token

    async def ainvoke(self, prompt, system_prompt=None, **kwargs):
        if self._fail:
            raise RuntimeError("LLM 模拟故障")
        return "".join(self._tokens)


@pytest.fixture()
def fake_llm(monkeypatch):
    """注入伪 LLM 到 llm_adapter 单例槽位"""
    fake = FakeLLM()
    monkeypatch.setattr(llm_adapter_module, "_llm_adapter", fake)
    return fake


@pytest.fixture()
def fake_retrieve(monkeypatch):
    """替换 retriever_agent.retrieve, 不依赖真实向量库"""

    async def _fake(question, kb_id, top_k=5):
        return {
            "chunks": [
                {"text": "Transformer 使用自注意力机制计算上下文", "doc_id": "doc1",
                 "page": 3, "doc_name": "transformer.pdf", "score": 0.81},
            ],
            "web_results": [],
        }

    monkeypatch.setattr(retriever_agent_module, "retrieve", _fake)
    return _fake


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """创建独立临时数据库的测试客户端"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config_module._config = None  # 重置模块级配置缓存
    database_module.engine = None
    database_module.SessionLocal = None

    from backend.core.database import init_database, get_db_session
    from backend.main import app
    from fastapi.testclient import TestClient

    init_database()
    session = get_db_session()
    Base.metadata.drop_all(session.get_bind())
    Base.metadata.create_all(session.get_bind())
    session.close()

    with TestClient(app) as client:
        yield client


@pytest.fixture()
def auth_headers(app_client):
    """注册并登录测试用户, 返回 Bearer 头"""
    resp = app_client.post("/api/v1/auth/register",
                           json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 200, resp.text
    resp = app_client.post("/api/v1/auth/login",
                           json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
