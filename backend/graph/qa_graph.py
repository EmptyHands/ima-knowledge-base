"""DEV-012: 问答 langgraph 管线 - retrieve/decide/ask_user/answer 四节点

人机交互闭环: 无可靠结果 → ask_user interrupt 挂起 → 用户确认后 resume →
allow_web_search=True → 边回到 retrieve 全量重跑(向量+联网)。
MemorySaver 以 thread_id=会话ID 跨 HTTP 请求保存状态(DEV-019 将换 redis)。
"""
import asyncio
from typing import Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from backend.agents import retriever_agent
from backend.core.database import get_db_session
from backend.core.llm_adapter import get_llm
from backend.core.retrieval import detect_web_intent
from backend.models.database import Conversation, Message
from backend.services import memory

HISTORY_LIMIT = 10

EMPTY_KB_FALLBACK = "当前知识库还没有任何文档。知识库中未找到与『{question}』相关的内容。是否需要联网搜索?回复『需要』即可。"
NO_RESULT_FALLBACK = "知识库中未找到与『{question}』相关的内容。是否需要联网搜索?回复『需要』即可。"
NO_ANSWER_FALLBACK = "未能基于检索内容生成回答。知识库中未找到与『{question}』相关的内容。是否需要联网搜索?回复『需要』即可。"
WEB_UNAVAILABLE = "联网搜索当前不可用(未配置 TAVILY_API_KEY), 请换个问法或上传相关文档后重试。"
NO_ANSWER_TERMINAL = "未能基于检索内容生成回答。请换个问法或上传相关文档后重试。"

ASK_STATUS = {
    "empty_kb": "知识库为空, 未进行检索",
    "no_result": "知识库中未检索到相关内容",
    "no_answer": "未能生成有效回答",
}


class QaState(TypedDict):
    question: str
    kb_id: str
    conv_id: str
    kb_empty: bool
    history: list[dict]            # [{"role", "content"}]
    allow_web_search: bool
    chunks: list[dict]
    web_results: list[dict]
    summary: Optional[str]
    answer: str
    citations: list[dict]
    ask_reason: Optional[str]      # empty_kb / no_result / no_answer
    fallback_text: Optional[str]


async def _retrieve(state: QaState) -> dict:
    """向量检索(关键词意图或已确认时联网)与摘要压缩并行, 取 max 延迟(DEV-015)"""
    allow_web = state["allow_web_search"] or detect_web_intent(state["question"])

    async def _search():
        # force_web 仅传用户确认的联网(与 chat 路由现状一致); 关键词意图由
        # retriever_agent.retrieve 内部 detect_web_intent 自行触发
        return await retriever_agent.retrieve(state["question"], state["kb_id"],
                                              force_web=state["allow_web_search"])

    async def _summarize():
        db = get_db_session()
        try:
            conv = db.query(Conversation).get(state["conv_id"])
            rows = db.query(Message).filter(Message.conversation_id == state["conv_id"]) \
                .order_by(Message.created_at.asc()).all()
            return await memory.update_summary(db, conv, rows, get_llm(), HISTORY_LIMIT)
        finally:
            db.close()

    chunks, summary = await asyncio.gather(
        _search(), _summarize() if state["conv_id"] else asyncio.sleep(0))
    return {"chunks": chunks["chunks"], "web_results": chunks["web_results"],
            "summary": summary, "allow_web_search": allow_web}


def _reliable(chunks: list, web_results: list) -> bool:
    return bool(chunks) or bool(web_results)


async def _decide(state: QaState) -> dict:
    """可靠性判定: 可靠走 answer; 已联网仍不可靠 → 终止文案(防死循环)"""
    if _reliable(state["chunks"], state["web_results"]):
        return {}
    if state["allow_web_search"]:
        return {"fallback_text": WEB_UNAVAILABLE}
    reason = "empty_kb" if state["kb_empty"] else "no_result"
    return {"ask_reason": reason}


def _route_after_retrieve(state: QaState) -> str:
    # 空库且未确认联网: 直接反问, 零检索零 LLM(与现状一致)
    if state["kb_empty"] and not state["allow_web_search"]:
        return "ask_user"
    if "chunks" not in state:
        return "retrieve"  # START: 尚未检索, 先跑 retrieve 节点
    if _reliable(state["chunks"], state["web_results"]):
        return "answer"
    if state["allow_web_search"]:
        return END  # 已联网仍无结果: 终止(防死循环)
    return "ask_user"


async def _ask_user(state: QaState) -> dict:
    raise NotImplementedError("ask_user 节点 Task 3 实现")


async def _answer(state: QaState) -> dict:
    raise NotImplementedError("answer 节点 Task 4 实现")


def build_graph(checkpointer=None):
    g = StateGraph(QaState)
    g.add_node("retrieve", _retrieve)
    g.add_node("decide", _decide)
    g.add_node("ask_user", _ask_user)   # Task 3 实现; 本任务先放占位(raise NotImplementedError)
    g.add_node("answer", _answer)       # Task 4 实现; 本任务先放占位
    g.add_conditional_edges(START, _route_after_retrieve,
                            {"retrieve": "retrieve", "ask_user": "ask_user", END: END})
    g.add_edge("retrieve", "decide")
    g.add_conditional_edges("decide", _route_after_retrieve,
                            {"answer": "answer", "ask_user": "ask_user", END: END})
    return g.compile(checkpointer=checkpointer or MemorySaver())


graph = build_graph()
