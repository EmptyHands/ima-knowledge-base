"""DEV-012: chat 路由 × langgraph 集成 - 人机交互闭环 / 线程清理 / 终止分支"""
import json

import pytest


def _parse_sse(body):
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


def _add_doc(db, kb_id):
    from backend.models.database import Document
    db.add(Document(id="doc-x", kb_id=kb_id, filename="x.pdf", file_path="/tmp/x.pdf"))
    db.commit()


@pytest.fixture()
def kb_id(app_client, auth_headers):
    resp = app_client.post("/api/v1/knowledge-bases",
                           json={"name": "图测试库", "description": ""}, headers=auth_headers)
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture()
def conv_id(app_client, auth_headers, kb_id):
    resp = app_client.post(f"/api/v1/conversations?kb_id={kb_id}",
                           json={"kb_id": kb_id, "title": "新对话"}, headers=auth_headers)
    assert resp.status_code == 200
    return resp.json()["id"]


def _empty_retrieve(monkeypatch):
    import backend.agents.retriever_agent as m
    calls = []

    async def _fake(question, kb_id, top_k=5, force_web=False):
        calls.append((question, force_web))
        if force_web:
            return {"chunks": [], "web_results": [{"title": "网", "url": "http://u", "snippet": "s"}]}
        return {"chunks": [], "web_results": []}

    monkeypatch.setattr(m, "retrieve", _fake)
    return calls


def test_full_human_loop(app_client, auth_headers, kb_id, conv_id, monkeypatch, fake_llm):
    """提问→反问→回复『需要』→联网回答: 两轮 SSE 完整闭环"""
    from backend.core.database import get_db_session
    db = get_db_session()
    _add_doc(db, kb_id)
    db.close()
    calls = _empty_retrieve(monkeypatch)

    r1 = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                         json={"question": "怎么种苹果"}, headers=auth_headers)
    ev1 = _parse_sse(r1.text)
    assert [e for e, _ in ev1] == ["status", "chunk", "citations", "done"]
    ask_text = "".join(d["text"] for e, d in ev1 if e == "chunk")
    assert "未找到与『怎么种苹果』相关的内容" in ask_text
    assert calls[-1] == ("怎么种苹果", False)

    r2 = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                         json={"question": "需要"}, headers=auth_headers)
    ev2 = _parse_sse(r2.text)
    assert [e for e, _ in ev2][-1] == "done"
    assert "chunk" in [e for e, _ in ev2]
    assert calls[-1] == ("怎么种苹果", True), "resume 后以原问题强制联网重跑"

    msgs = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                          headers=auth_headers).json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


def test_new_question_after_ask_cleans_thread(app_client, auth_headers, kb_id, conv_id,
                                              monkeypatch, fake_llm):
    """反问后回复新问题(非确认词): 丢弃中断态, 正常新 run"""
    from backend.core.database import get_db_session
    db = get_db_session()
    _add_doc(db, kb_id)
    db.close()
    calls = _empty_retrieve(monkeypatch)

    app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                    json={"question": "怎么种苹果"}, headers=auth_headers)
    r2 = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                         json={"question": "什么是番茄"}, headers=auth_headers)
    ev2 = _parse_sse(r2.text)
    assert "chunk" in [e for e, _ in ev2]
    assert calls[-1] == ("什么是番茄", False), "新问题不应继承联网开关"


def test_confirmed_web_unavailable_terminal(app_client, auth_headers, kb_id, conv_id,
                                            monkeypatch, fake_llm):
    """确认联网但检索仍空(未配密钥→web 空): 终止文案, 不再反问"""
    from backend.core.database import get_db_session
    db = get_db_session()
    _add_doc(db, kb_id)
    db.close()
    import backend.agents.retriever_agent as m

    async def _always_empty(question, kb_id, top_k=5, force_web=False):
        return {"chunks": [], "web_results": []}

    monkeypatch.setattr(m, "retrieve", _always_empty)

    app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                    json={"question": "怎么种苹果"}, headers=auth_headers)
    r2 = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                         json={"question": "需要"}, headers=auth_headers)
    ev2 = _parse_sse(r2.text)
    assert [e for e, _ in ev2] == ["status", "chunk", "citations", "done"]
    text = "".join(d["text"] for e, d in ev2 if e == "chunk")
    assert "联网搜索当前不可用" in text
    assert "是否需要联网" not in text, "终止分支不再反问(防死循环)"
    msgs = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                          headers=auth_headers).json()
    assert "联网搜索当前不可用" in msgs[-1]["content"]


def test_resume_after_thread_lost_falls_back(app_client, auth_headers, kb_id, conv_id,
                                             monkeypatch, fake_llm):
    """模拟进程重启(线程丢失): 确认词 resume 失败 → 降级新 run 仍能联网回答"""
    from backend.core.database import get_db_session
    db = get_db_session()
    _add_doc(db, kb_id)
    db.close()
    calls = _empty_retrieve(monkeypatch)

    app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                    json={"question": "怎么种苹果"}, headers=auth_headers)
    # 清掉线程, 模拟进程重启丢内存态 (langgraph 1.2.11 的 adelete_thread 接受 thread_id 字符串)
    from backend.graph import qa_graph
    import asyncio
    asyncio.run(qa_graph.checkpointer.adelete_thread(conv_id))

    r2 = app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                         json={"question": "需要"}, headers=auth_headers)
    ev2 = _parse_sse(r2.text)
    assert "chunk" in [e for e, _ in ev2]
    assert calls[-1] == ("怎么种苹果", True), "线程丢失应降级为带联网的新 run"
