"""检索无结果兜底机制测试 - 空库反问 / 无结果反问 / 确认联网闭环"""
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
                           json={"name": "兜底测试库", "description": ""},
                           headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.fixture()
def conv_id(app_client, auth_headers, kb_id):
    resp = app_client.post(f"/api/v1/conversations?kb_id={kb_id}",
                           json={"kb_id": kb_id, "title": "新对话"},
                           headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _ask(app_client, conv_id, question, headers):
    return app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={"question": question}, headers=headers)


def test_empty_kb_asks_web_fallback(app_client, auth_headers, kb_id, conv_id):
    """空库: 固定反问, 事件序列 status -> chunk -> citations -> done"""
    resp = _ask(app_client, conv_id, "什么是机器学习", auth_headers)
    events = _parse_sse(resp.text)
    types = [e for e, _ in events]
    assert types == ["status", "chunk", "citations", "done"]
    # 兜底文本必须走 chunk 下发, 前端才无需刷新即可显示
    answer = "".join(data["text"] for e, data in events if e == "chunk")
    assert "还没有任何文档" in answer
    msg = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                         headers=auth_headers).json()
    assert msg[1]["role"] == "assistant"
    assert "还没有任何文档" in msg[1]["content"]
    assert "是否需要联网搜索" in msg[1]["content"]


def test_fallback_title_from_question(app_client, auth_headers, kb_id, conv_id):
    """空库反问分支: 自动标题取用户问题截断, 而非兜底回复原文 (DEV-009)"""
    question = "这是一句超过二十个字的问题用于验证兜底标题截取逻辑是否正确生效"
    _ask(app_client, conv_id, question, auth_headers)
    convs = app_client.get(f"/api/v1/conversations?kb_id={kb_id}", headers=auth_headers).json()
    assert convs[0]["title"] == question[:20]


def test_no_result_asks_web_fallback(app_client, auth_headers, kb_id, conv_id, monkeypatch):
    """有文档但检索全空: 反问带原问题"""
    from backend.models.database import Document
    from backend.core.database import get_db_session
    db = get_db_session()
    db.add(Document(id="doc-x", kb_id=kb_id, filename="x.pdf", file_path="/tmp/x.pdf"))
    db.commit()
    db.close()

    import backend.agents.retriever_agent as retriever_module

    async def _empty(question, kb_id, top_k=5, force_web=False):
        return {"chunks": [], "web_results": []}

    monkeypatch.setattr(retriever_module, "retrieve", _empty)

    resp = _ask(app_client, conv_id, "怎么种苹果", auth_headers)
    events = _parse_sse(resp.text)
    types = [e for e, _ in events]
    assert types[0] == "status"
    assert "chunk" in types
    assert types[-2] == "citations"
    assert types[-1] == "done"
    # 兜底文本走 chunk 下发, 含原问题供确认词轮次提取
    answer = "".join(data["text"] for e, data in events if e == "chunk")
    assert "未找到与『怎么种苹果』相关的内容" in answer
    msg = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                         headers=auth_headers).json()
    assert "未找到与『怎么种苹果』相关的内容" in msg[1]["content"]


def test_confirm_word_triggers_force_web(app_client, auth_headers, kb_id, conv_id,
                                         monkeypatch, fake_llm):
    """反问后回复确认词: 提取原问题并强制联网"""
    from backend.models.database import Document
    from backend.core.database import get_db_session
    db = get_db_session()
    db.add(Document(id="doc-x", kb_id=kb_id, filename="x.pdf", file_path="/tmp/x.pdf"))
    db.commit()
    db.close()

    import backend.agents.retriever_agent as retriever_module

    calls = []

    async def _fake_retrieve(question, kb_id, top_k=5, force_web=False):
        calls.append((question, force_web))
        if force_web:
            return {"chunks": [], "web_results": [{"title": "网络结果", "url": "http://x", "snippet": "s"}]}
        return {"chunks": [], "web_results": []}

    monkeypatch.setattr(retriever_module, "retrieve", _fake_retrieve)

    # 第一轮: 无结果反问
    _ask(app_client, conv_id, "怎么种苹果", auth_headers)

    # 第二轮: 回复确认词
    resp = _ask(app_client, conv_id, "需要", auth_headers)
    events = _parse_sse(resp.text)
    assert "chunk" in [e for e, _ in events]
    assert calls[-1] == ("怎么种苹果", True), "应提取原问题并强制联网"


def test_non_confirm_reply_not_force_web(app_client, auth_headers, kb_id, conv_id, monkeypatch):
    """非确认词回复: 不触发强制联网"""
    from backend.models.database import Document
    from backend.core.database import get_db_session
    db = get_db_session()
    db.add(Document(id="doc-x", kb_id=kb_id, filename="x.pdf", file_path="/tmp/x.pdf"))
    db.commit()
    db.close()

    import backend.agents.retriever_agent as retriever_module

    calls = []

    async def _fake_retrieve(question, kb_id, top_k=5, force_web=False):
        calls.append((question, force_web))
        return {"chunks": [], "web_results": []}

    monkeypatch.setattr(retriever_module, "retrieve", _fake_retrieve)

    _ask(app_client, conv_id, "怎么种苹果", auth_headers)
    _ask(app_client, conv_id, "明天再说", auth_headers)
    assert calls[-1] == ("明天再说", False)


def test_confirmed_but_web_unavailable(app_client, auth_headers, kb_id, conv_id, monkeypatch):
    """确认联网但未配置网络搜索: 固定提示不可用"""
    import backend.agents.retriever_agent as retriever_module

    async def _empty(question, kb_id, top_k=5, force_web=False):
        return {"chunks": [], "web_results": []}

    monkeypatch.setattr(retriever_module, "retrieve", _empty)
    _ask(app_client, conv_id, "怎么种苹果", auth_headers)
    resp = _ask(app_client, conv_id, "需要", auth_headers)
    msg = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                         headers=auth_headers).json()
    assert "联网搜索" in msg[-1]["content"]


def test_empty_llm_output_falls_back(app_client, auth_headers, kb_id, conv_id, monkeypatch):
    """检索有片段但 LLM 流式输出为空: 回退反问模板, 不落空消息(刷新后无空白气泡)"""
    from backend.models.database import Document
    from backend.core.database import get_db_session
    db = get_db_session()
    db.add(Document(id="doc-empty-llm", kb_id=kb_id, filename="x.pdf", file_path="/tmp/x.pdf"))
    db.commit()
    db.close()

    import backend.agents.retriever_agent as retriever_module

    async def _fake_retrieve(question, kb_id, top_k=5, force_web=False):
        return {"chunks": [{"text": "Transformer 使用自注意力机制", "doc_id": "doc1",
                            "page": 1, "doc_name": "t.pdf", "score": 0.7}],
                "web_results": []}

    monkeypatch.setattr(retriever_module, "retrieve", _fake_retrieve)

    from backend.core import llm_adapter

    class EmptyLLM:
        async def astream(self, messages, system_prompt=None):
            for _ in []:
                yield ""

        async def ainvoke(self, messages, system_prompt=None, **kwargs):
            return ""

    monkeypatch.setattr(llm_adapter, "_llm_adapter", EmptyLLM())

    resp = _ask(app_client, conv_id, "当前问题无法回答", auth_headers)
    events = _parse_sse(resp.text)
    types = [e for e, _ in events]
    assert "chunk" in types
    assert types[-2] == "citations"
    assert types[-1] == "done"
    # 兜底文本走 chunk 下发, 含原问题供确认词轮次提取
    answer = "".join(data["text"] for e, data in events if e == "chunk")
    assert "未找到与『当前问题无法回答』相关的内容" in answer
    msgs = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                          headers=auth_headers).json()
    assistant = [m for m in msgs if m["role"] == "assistant"]
    assert assistant, "应有助手兜底消息"
    assert assistant[-1]["content"].strip(), "兜底消息非空, 刷新后不应出现空白气泡"
