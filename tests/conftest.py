"""pytest 共享 fixture - 每次测试用独立临时 SQLite 数据库"""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import backend.core.config as config_module
import backend.core.database as database_module
from backend.models.database import Base


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
