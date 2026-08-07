"""知识库 CRUD 测试 - 创建/列表/更新/删除 + 用户隔离"""
import pytest


@pytest.fixture()
def create_kb(app_client, auth_headers):
    def _create(name="测试知识库", description="描述"):
        resp = app_client.post("/api/v1/knowledge-bases",
                               json={"name": name, "description": description},
                               headers=auth_headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _create


def test_create_kb(create_kb):
    kb = create_kb()
    assert kb["id"]
    assert kb["name"] == "测试知识库"


def test_list_kbs_only_own(app_client, auth_headers, create_kb):
    create_kb("我的库")
    # 第二个用户登录后列表应为空
    app_client.post("/api/v1/auth/register",
                    json={"username": "bob", "password": "secret123"})
    resp = app_client.post("/api/v1/auth/login",
                           json={"username": "bob", "password": "secret123"})
    bob_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = app_client.get("/api/v1/knowledge-bases", headers=bob_headers)
    assert resp.json() == []


def test_update_kb(app_client, auth_headers, create_kb):
    kb = create_kb()
    resp = app_client.put(f"/api/v1/knowledge-bases/{kb['id']}",
                          json={"name": "改名", "description": "新描述"},
                          headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "改名"


def test_delete_kb(app_client, auth_headers, create_kb):
    kb = create_kb()
    resp = app_client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=auth_headers)
    assert resp.status_code == 200
    resp = app_client.get("/api/v1/knowledge-bases", headers=auth_headers)
    assert resp.json() == []


def test_kb_isolated_across_users(app_client, auth_headers, create_kb):
    kb = create_kb()
    app_client.post("/api/v1/auth/register",
                    json={"username": "bob", "password": "secret123"})
    resp = app_client.post("/api/v1/auth/login",
                           json={"username": "bob", "password": "secret123"})
    bob_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    assert app_client.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=bob_headers).status_code == 404
    assert app_client.put(f"/api/v1/knowledge-bases/{kb['id']}",
                          json={"name": "x", "description": ""},
                          headers=bob_headers).status_code == 404
    assert app_client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=bob_headers).status_code == 404
