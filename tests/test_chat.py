"""会话/消息 API 测试 - 创建会话/列表/消息/占位 SSE"""
import pytest


@pytest.fixture()
def kb_id(app_client, auth_headers):
    resp = app_client.post("/api/v1/knowledge-bases",
                           json={"name": "聊天测试库", "description": ""},
                           headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_create_and_list_conversations(app_client, auth_headers, kb_id):
    resp = app_client.post(f"/api/v1/conversations?kb_id={kb_id}",
                           json={"kb_id": kb_id, "title": "第一个对话"},
                           headers=auth_headers)
    assert resp.status_code == 200
    conv_id = resp.json()["id"]

    resp = app_client.get(f"/api/v1/conversations?kb_id={kb_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["id"] == conv_id


def test_ask_returns_sse_stream(app_client, auth_headers, kb_id):
    resp = app_client.post(f"/api/v1/conversations?kb_id={kb_id}",
                           json={"kb_id": kb_id, "title": "对话"},
                           headers=auth_headers)
    conv_id = resp.json()["id"]

    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           headers=auth_headers)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "event: status" in body
    assert "event: done" in body


def test_ask_on_others_conversation_404(app_client, auth_headers, kb_id):
    resp = app_client.post(f"/api/v1/conversations?kb_id={kb_id}",
                           json={"kb_id": kb_id, "title": "我的对话"},
                           headers=auth_headers)
    conv_id = resp.json()["id"]
    app_client.post("/api/v1/auth/register",
                    json={"username": "bob", "password": "secret123"})
    resp = app_client.post("/api/v1/auth/login",
                           json={"username": "bob", "password": "secret123"})
    bob_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages", headers=bob_headers)
    assert resp.status_code == 404


def test_delete_conversation(app_client, auth_headers, kb_id):
    resp = app_client.post(f"/api/v1/conversations?kb_id={kb_id}",
                           json={"kb_id": kb_id, "title": "待删除"},
                           headers=auth_headers)
    conv_id = resp.json()["id"]
    resp = app_client.delete(f"/api/v1/conversations/{conv_id}", headers=auth_headers)
    assert resp.status_code == 200
    resp = app_client.get(f"/api/v1/conversations?kb_id={kb_id}", headers=auth_headers)
    assert resp.json() == []
