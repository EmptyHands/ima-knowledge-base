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
        async def astream(self, messages, system_prompt=None):
            raise RuntimeError("LLM 模拟故障")

        async def ainvoke(self, messages, system_prompt=None, **kwargs):
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


def test_web_citation_clickable_via_citations_event(app_client, auth_headers, conv_id, monkeypatch):
    """DEV-018: 联网回答的 [n] 角标映射到网络结果, citations 事件含 url 且随消息落库"""
    from backend.core.llm_adapter import LLMProvider

    class WebLLM(LLMProvider):
        async def astream(self, messages, system_prompt=None):
            for token in ["根据", "网络", "搜索[1]", "的回答", "\n## 引用\n", "[1] T1 (https://a.com)"]:
                yield token

        async def ainvoke(self, messages, system_prompt=None, **kwargs):
            return "".join(self._tokens)

    import backend.core.llm_adapter as llm_adapter_module
    monkeypatch.setattr(llm_adapter_module, "_llm_adapter", WebLLM())

    async def _fake_retrieve_web(question, kb_id, top_k=5, force_web=False):
        return {
            "chunks": [],
            "web_results": [{"title": "T1", "url": "https://a.com", "snippet": "s1"}],
        }

    import backend.agents.retriever_agent as retriever_agent_module
    monkeypatch.setattr(retriever_agent_module, "retrieve", _fake_retrieve_web)

    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={"question": "当前技术热点"}, headers=auth_headers)
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1][0] == "done"

    citations_event = dict(events)["citations"]
    assert len(citations_event["items"]) == 1
    item = citations_event["items"][0]
    assert item["n"] == 1
    assert item["doc_name"] == "T1"
    assert item["url"] == "https://a.com"
    assert item["verified"] is True

    messages = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                              headers=auth_headers).json()
    assert messages[1]["citations_json"][0]["url"] == "https://a.com"


def test_ask_requires_question(app_client, auth_headers, conv_id):
    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={}, headers=auth_headers)
    assert resp.status_code == 422


class RecordingLLM:
    """记录 ainvoke 调用与 astream 收到的消息 (DEV-015)"""

    def __init__(self):
        self.ainvoke_calls = []
        self.stream_messages = None

    async def ainvoke(self, messages, system_prompt=None, **kwargs):
        self.ainvoke_calls.append((list(messages), system_prompt))
        return "压缩后的对话摘要"

    async def astream(self, messages, system_prompt=None):
        self.stream_messages = list(messages)
        for token in ["基于", "片段", "[1]", "的回答", "\n## 引用\n", "[1] transformer.pdf, 第3页"]:
            yield token


def _insert_messages(db, conv_id, n):
    from backend.models.database import Message
    for i in range(n):
        db.add(Message(conversation_id=conv_id, role="user" if i % 2 == 0 else "assistant",
                       content=f"历史消息{i}"))
    db.commit()


def test_long_conversation_compresses_and_injects_summary(app_client, auth_headers, conv_id,
                                                          fake_retrieve, monkeypatch):
    """DEV-015: 15 条历史(窗口外 5 条) → 压缩被调用, summary 落库, 回答请求首条为 system 摘要"""
    from backend.core.database import get_db_session
    from backend.models.database import Conversation
    db = get_db_session()
    _insert_messages(db, conv_id, 15)
    db.close()

    llm = RecordingLLM()
    import backend.core.llm_adapter as llm_adapter_module
    monkeypatch.setattr(llm_adapter_module, "_llm_adapter", llm)

    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={"question": "当前进展如何"}, headers=auth_headers)
    assert resp.status_code == 200
    assert dict(_parse_sse(resp.text))["done"]

    assert len(llm.ainvoke_calls) == 1, "压缩必须调用一次 LLM"
    assert "历史消息0" in llm.ainvoke_calls[0][0][0].content, "窗口外历史进入压缩输入"
    assert llm.stream_messages[0].role == "system"
    assert "压缩后的对话摘要" in llm.stream_messages[0].content

    db = get_db_session()
    conv = db.query(Conversation).get(conv_id)
    assert conv.summary == "压缩后的对话摘要"
    assert conv.summary_until_id
    db.close()


def test_short_conversation_skips_compression(app_client, auth_headers, conv_id,
                                              fake_retrieve, monkeypatch):
    """DEV-015: 短会话(≤10 条)零压缩调用"""
    from backend.core.database import get_db_session
    db = get_db_session()
    _insert_messages(db, conv_id, 4)
    db.close()
    llm = RecordingLLM()
    import backend.core.llm_adapter as llm_adapter_module
    monkeypatch.setattr(llm_adapter_module, "_llm_adapter", llm)
    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={"question": "你好"}, headers=auth_headers)
    assert resp.status_code == 200
    assert llm.ainvoke_calls == [], "短会话不触发压缩"


def test_empty_kb_fallback_skips_compression(app_client, auth_headers, monkeypatch):
    """DEV-015: 空库兜底分支不触发压缩(零 LLM 成本)"""
    resp = app_client.post("/api/v1/knowledge-bases", json={"name": "空库", "description": ""},
                           headers=auth_headers)
    kb_id = resp.json()["id"]
    resp = app_client.post(f"/api/v1/conversations?kb_id={kb_id}",
                           json={"kb_id": kb_id, "title": "新对话"}, headers=auth_headers)
    conv_id = resp.json()["id"]
    llm = RecordingLLM()
    import backend.core.llm_adapter as llm_adapter_module
    monkeypatch.setattr(llm_adapter_module, "_llm_adapter", llm)
    resp = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={"question": "有什么"}, headers=auth_headers)
    assert resp.status_code == 200
    assert "chunk" in [e for e, _ in _parse_sse(resp.text)]
    assert llm.ainvoke_calls == [], "fallback 不触发压缩"
