"""SSE 流式问答端点测试 - 伪 LLM + 伪检索, 断言完整事件序列与消息持久化"""
import json

import pytest


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event is not None:
            events.append((event, data))
    return events


@pytest.fixture()
def kb_id(app_client, auth_headers):
    resp = app_client.post("/api/v1/knowledge-bases",
                           json={"name": "流式测试库", "description": ""},
                           headers=auth_headers)
    assert resp.status_code == 200, resp.text
    kb_id = resp.json()["id"]
    # 非空知识库: 附带一个文档, 使提问走正常检索链路而非空库反问
    from backend.core.database import get_db_session
    from backend.models.database import Document
    db = get_db_session()
    db.add(Document(id=f"doc-{kb_id}", kb_id=kb_id, filename="stream.pdf",
                    file_path="/tmp/stream.pdf"))
    db.commit()
    db.close()
    return kb_id


@pytest.fixture()
def conv_id(app_client, auth_headers, kb_id):
    resp = app_client.post(f"/api/v1/conversations?kb_id={kb_id}",
                           json={"kb_id": kb_id, "title": "新对话"},
                           headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_sse_event_sequence_and_persistence(app_client, auth_headers, conv_id, fake_llm, fake_retrieve):
    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={"question": "Transformer 使用什么机制"},
                           headers=auth_headers)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events = _parse_sse(resp.text)
    types = [e for e, _ in events]
    assert types[0] == "status"
    assert "chunk" in types
    assert types[-2] == "citations"
    assert types[-1] == "done"

    answer = "".join(data["text"] for e, data in events if e == "chunk")
    assert "基于片段[1]的回答" in answer

    citations_event = dict(events)["citations"]
    assert citations_event["items"][0]["doc_name"] == "transformer.pdf"
    assert citations_event["items"][0]["page"] == 3

    message_id = dict(events)["done"]["message_id"]
    assert message_id

    messages = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                              headers=auth_headers).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["citations_json"][0]["doc_name"] == "transformer.pdf"


def test_auto_title_from_question(app_client, auth_headers, kb_id, conv_id, fake_llm, fake_retrieve):
    question = "这是一句超过二十个字的问题用于验证自动标题截取逻辑是否正确生效"
    app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                    json={"question": question}, headers=auth_headers)
    convs = app_client.get(f"/api/v1/conversations?kb_id={kb_id}", headers=auth_headers).json()
    assert convs[0]["title"] == question[:20]


def test_error_event_when_llm_fails(app_client, auth_headers, conv_id, fake_retrieve, monkeypatch):
    from backend.core.llm_adapter import LLMProvider

    class FailingLLM(LLMProvider):
        async def astream(self, prompt, system_prompt=None):
            raise RuntimeError("LLM 模拟故障")

        async def ainvoke(self, prompt, system_prompt=None, **kwargs):
            raise RuntimeError("LLM 模拟故障")

    import backend.core.llm_adapter as llm_adapter_module
    monkeypatch.setattr(llm_adapter_module, "_llm_adapter", FailingLLM())

    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={"question": "会不会失败"}, headers=auth_headers)
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1][0] == "error"
    assert "生成失败" in events[-1][1]["text"]

    # 失败时用户消息已入库, 无助手消息
    messages = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                              headers=auth_headers).json()
    assert [m["role"] for m in messages] == ["user"]


def test_ask_requires_question(app_client, auth_headers, conv_id):
    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={}, headers=auth_headers)
    assert resp.status_code == 422
