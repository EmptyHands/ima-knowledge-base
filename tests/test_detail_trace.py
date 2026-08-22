"""DEV-022: 详细日志开关与采集内容测试"""
import re

import pytest

TS_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] ")


@pytest.fixture()
def trace_env(monkeypatch, tmp_path):
    """开启详细日志: 注入 env + 重置 config 缓存, 返回日志路径"""
    import backend.core.config as config_module
    monkeypatch.setenv("DETAIL_LOG_ENABLED", "true")
    log_path = tmp_path / "logs" / "detail.log"
    monkeypatch.setenv("DETAIL_LOG_PATH", str(log_path))
    config_module._config = None
    return log_path


@pytest.mark.asyncio
async def test_begin_capture_finish_writes_log(trace_env):
    import backend.utils.detail_trace as dt
    dt.begin({"question": "q1", "kb_id": "kb1", "conv_id": "c1",
              "is_confirm": False, "history": "h"})
    dt.capture_node("retrieve", {"question": "q1", "kb_empty": False,
                                 "allow_web_search": False, "chunks": [], "web_results": []})
    dt.capture_decision("route", "answer")
    dt.capture_tool("vector_search", {"kb_id": "kb1", "question": "q1", "top_k": 5},
                    {"chunks": []}, 0.312)
    dt.capture_retrieval({"kb_id": "kb1", "question": "q1", "top_k": 5},
                         "dense 最高分=0.72 >= 阈值0.35 → 走 dense", [])
    dt.capture_llm("stream", "user: hi", "思考过程内容", 4.2)
    dt.finish({"answer": "回答内容", "citations": [1, 2], "branch": "answer"})

    text = trace_env.read_text(encoding="utf-8")
    assert "问答 #c1" in text
    for marker in ("[请求]", "[节点] retrieve", "[决策] route → answer",
                   "[工具] vector_search", "[检索]", "[LLM] stream", "[思考]",
                   "[结果]", "[耗时]"):
        assert marker in text, marker
    assert "思考过程内容" in text
    assert "回答内容" in text


@pytest.mark.asyncio
async def test_all_event_lines_have_ms_timestamp(trace_env):
    import backend.utils.detail_trace as dt
    dt.begin({"question": "q", "conv_id": "c"})
    dt.capture_node("retrieve", {})
    dt.capture_decision("route", "answer")
    dt.capture_tool("t", {}, {}, 0.1)
    dt.capture_retrieval({}, "d", [])
    dt.capture_llm("stream", "m", "r", 1.0)
    dt.finish({"answer": "a", "citations": [], "branch": "answer"})
    for line in trace_env.read_text(encoding="utf-8").splitlines():
        if line.startswith("[") and line.count("]") >= 2:
            assert TS_RE.match(line), line


@pytest.mark.asyncio
async def test_disabled_no_file(monkeypatch, tmp_path):
    import backend.core.config as config_module
    monkeypatch.setenv("DETAIL_LOG_ENABLED", "false")
    monkeypatch.setenv("DETAIL_LOG_PATH", str(tmp_path / "detail.log"))
    config_module._config = None
    import backend.utils.detail_trace as dt
    assert dt.trace_enabled() is False
    dt.begin({"question": "q", "conv_id": "c"})
    dt.capture_node("retrieve", {})
    dt.capture_llm("stream", "m", "r", 1.0)
    dt.finish({"answer": "a", "citations": [], "branch": "answer"})
    assert not (tmp_path / "detail.log").exists()


@pytest.mark.asyncio
async def test_finish_write_failure_tolerated(trace_env, monkeypatch):
    """写失败仅 warning, 不抛异常; finish 幂等(重复调用不写两份)"""
    import backend.utils.detail_trace as dt
    monkeypatch.setattr(dt.Path, "open", lambda self, *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    dt.begin({"question": "q", "conv_id": "c"})
    dt.capture_node("retrieve", {})
    dt.finish({"answer": "a", "citations": [], "branch": "answer"})
    dt.finish({"answer": "a", "citations": [], "branch": "answer"})  # 幂等: 第二次 no-op


@pytest.mark.asyncio
async def test_long_text_truncated(trace_env):
    import backend.utils.detail_trace as dt
    long = "长" * 2000
    dt.begin({"question": long, "conv_id": "c", "history": long})
    dt.capture_retrieval({}, "d", [{"score": 0.9, "page": 1, "text": long}])
    dt.capture_llm("stream", long, long, 1.0)
    dt.finish({"answer": long, "citations": [], "branch": "answer"})
    text = trace_env.read_text(encoding="utf-8")
    assert "截断" in text
    assert "长" * 2000 not in text


@pytest.mark.asyncio
async def test_registry_call_captures_tool(trace_env, monkeypatch):
    """registry.call 记录工具名/参数/结果/耗时"""
    import backend.core.retrieval as retrieval_module
    from backend.mcp.registry import registry
    import backend.utils.detail_trace as dt

    async def _fake_vs(kb_id, question, top_k=None):
        return [{"score": 0.9, "text": "t", "doc_id": "d1", "page": 1, "chunk_index": 0}]

    monkeypatch.setattr(retrieval_module, "vector_search", _fake_vs)
    dt.begin({"question": "q", "conv_id": "c"})
    result = await registry.call("vector_search", {"kb_id": "kb1", "question": "q", "top_k": 3})
    dt.finish({"answer": "a", "citations": [], "branch": "answer"})

    assert result["chunks"][0]["score"] == 0.9
    text = trace_env.read_text(encoding="utf-8")
    assert "[工具] vector_search" in text
    assert "kb1" in text
    assert "耗时=" in text
