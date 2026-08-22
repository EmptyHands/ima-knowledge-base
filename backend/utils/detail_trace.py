"""DEV-022: 可配置详细日志 - contextvar 请求级 trace, 关闭时零开销

开关由 config.detail_log_enabled 控制(从 .env 读取, 重启生效);
开启时 chat 路由请求入口 begin(), 各插桩点按事件时序采集,
请求结束 finish() 序列化为可读文本 append 到单文件 detail.log。
"""
import logging
import time
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from backend.core.config import get_config

logger = logging.getLogger(__name__)

MAX_TEXT = 800
MAX_HISTORY_ITEM = 500

_current_trace: ContextVar["DetailTrace | None"] = ContextVar("detail_trace", default=None)


def trunc(text, limit=MAX_TEXT) -> str:
    s = str(text)
    return s if len(s) <= limit else f"{s[:limit]}...(截断 {len(s) - limit} 字)"


def trace_enabled() -> bool:
    return _current_trace.get() is not None


class DetailTrace:
    def __init__(self, request: dict, log_path: str):
        self.request = request
        self.log_path = log_path
        self.events: list[str] = []
        self.started = time.perf_counter()

    def add(self, kind: str, text: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.events.append(f"[{ts}] [{kind}] {text}")

    def render(self, result: dict | None) -> str:
        req = self.request
        lines = [
            "=" * 40,
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 问答 #{req.get('conv_id', '?')}",
            "-" * 40,
            f"[请求] question={trunc(req.get('question', ''), 200)} "
            f"kb_id={req.get('kb_id', '')} conv_id={req.get('conv_id', '')} "
            f"is_confirm={req.get('is_confirm', False)} "
            f"history={trunc(req.get('history', ''), MAX_HISTORY_ITEM)}",
        ]
        lines.extend(self.events)
        if result:
            if result.get("error"):
                lines.append(f"[错误] {result['error']}")
            else:
                lines.append(f"[结果] answer={trunc(result.get('answer', ''), MAX_TEXT)} "
                             f"citations={len(result.get('citations') or [])}条 "
                             f"分支={result.get('branch', '?')}")
        lines.append(f"[耗时] 总计 {time.perf_counter() - self.started:.1f}s")
        lines.append("=" * 40)
        return "\n".join(lines)


def begin(request: dict) -> None:
    config = get_config()
    if not config.detail_log_enabled:
        return
    _current_trace.set(DetailTrace(request, config.detail_log_path))


def capture_node(name: str, state: dict) -> None:
    t = _current_trace.get()
    if t is None:
        return
    t.add("节点", f"{name} 进入 question={trunc(state.get('question', ''), 200)} "
                 f"kb_empty={state.get('kb_empty')} allow_web={state.get('allow_web_search')} "
                 f"chunks={len(state.get('chunks') or [])} "
                 f"web_results={len(state.get('web_results') or [])} "
                 f"ask_reason={state.get('ask_reason')}")


def capture_decision(label: str, detail: str) -> None:
    t = _current_trace.get()
    if t is None:
        return
    t.add("决策", f"{label} → {trunc(detail, 300)}")


def capture_tool(name: str, arguments: dict, result: dict, elapsed: float) -> None:
    t = _current_trace.get()
    if t is None:
        return
    t.add("工具", f"{name} 参数={trunc(arguments, 300)} "
                 f"耗时={elapsed * 1000:.0f}ms 结果={trunc(result, 300)}")


def capture_retrieval(query: dict, decision: str, chunks: list) -> None:
    t = _current_trace.get()
    if t is None:
        return
    t.add("检索", f"查询={trunc(query, 200)} {decision}")
    if chunks:
        brief = " ".join(
            f"[{c.get('score', '?')}] 第{c.get('page', '?')}页 {trunc(c.get('text', ''), 80)}"
            for c in chunks)
        t.add("检索", f"结果 {len(chunks)} 条: {brief}")


def capture_llm(kind: str, messages_summary: str, reasoning: str,
                elapsed: float, token_count=None) -> None:
    t = _current_trace.get()
    if t is None:
        return
    tokens = f" tokens={token_count}" if token_count else ""
    t.add("LLM", f"{kind} 消息={trunc(messages_summary, 400)} "
                 f"耗时={elapsed:.1f}s{tokens}")
    if reasoning.strip():
        t.add("思考", f"reasoning_content(截断{MAX_TEXT}字)={trunc(reasoning)}")


def finish(result: dict | None = None) -> None:
    t = _current_trace.get()
    if t is None:
        return
    _current_trace.set(None)  # 先复位, 防写失败/重复 finish 重复落盘
    text = t.render(result)
    try:
        path = Path(t.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError as e:
        logger.warning(f"详细日志写入失败({t.log_path}): {e}")
