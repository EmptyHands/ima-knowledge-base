"""DEV-012: 问答 langgraph 管线 - retrieve/decide/ask_user/answer 四节点

人机交互闭环: 无可靠结果 → ask_user interrupt 挂起 → 用户确认后 resume →
allow_web_search=True → 边回到 retrieve 全量重跑(向量+联网)。
checkpointer 以 thread_id=会话ID 跨 HTTP 请求保存状态(DEV-019 换 redis,
不可用自动降级 MemorySaver)。
"""
import asyncio
import logging
from typing import Optional, TypedDict

from langchain_core.runnables.config import var_child_runnable_config
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from backend.agents import retriever_agent
from backend.core.config import get_config
from backend.core.database import get_db_session
from backend.core.llm_adapter import get_llm
from backend.core.retrieval import detect_web_intent
from backend.models.database import Conversation, Message
from backend.services import memory

logger = logging.getLogger(__name__)

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

ASK_TEXT = {
    "empty_kb": EMPTY_KB_FALLBACK,
    "no_result": NO_RESULT_FALLBACK,
    "no_answer": NO_ANSWER_FALLBACK,
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


async def _ask_user(state: QaState, config=None) -> dict:
    """人机交互: 下发反问状态与文案后 interrupt 挂起; resume 后开联网开关

    注: langgraph 1.2.11 在 Python 3.10 下异步节点不注入 config 上下文
    (CONTEXT_NOT_SUPPORTED = sys.version_info < (3, 11)),
    get_config() 拿不到 var_child_runnable_config 会使 interrupt/get_stream_writer
    报 "Called get_config outside of a runnable context", 故手动注入节点 config。
    """
    token = var_child_runnable_config.set(config) if config else None
    try:
        reason = state.get("ask_reason") or ("empty_kb" if state["kb_empty"] else "no_result")
        text = ASK_TEXT[reason].format(question=state["question"])
        get_stream_writer()({"type": "status", "data": ASK_STATUS[reason]})
        interrupt({"text": text})
        return {"allow_web_search": True, "fallback_text": text}
    finally:
        if token is not None:
            var_child_runnable_config.reset(token)


async def _answer(state: QaState, config=None) -> dict:
    """LLM 流式回答 + 引用校验; token 经 custom 流实时外发

    注: langgraph 1.2.11 在 Python 3.10 下异步节点不注入 config 上下文
    (CONTEXT_NOT_SUPPORTED), get_stream_writer() 需手动注入节点 config,
    模式与 _ask_user 相同。
    """
    from backend.agents import answer_agent
    from backend.models.messages import ChatMessage

    token = var_child_runnable_config.set(config) if config else None
    try:
        writer = get_stream_writer()
        history = [ChatMessage(role=h["role"], content=h["content"]) for h in state["history"]]
        answer_parts, citations = [], []
        async for event in answer_agent.stream(state["question"], history, state["chunks"],
                                               state["web_results"], summary=state.get("summary")):
            writer(event)
            if event["type"] == "chunk":
                answer_parts.append(event["data"])
            elif event["type"] == "citations":
                citations = event["data"]
        answer = "".join(answer_parts).strip()
        if answer:
            return {"answer": answer, "citations": citations}
        if state["allow_web_search"]:
            # 显式写 ask_reason=None: langgraph 1.2.11 的 TypedDict 通道只物化
            # 被写入过的键, 不写则 final["ask_reason"] 报 KeyError
            return {"answer": "", "citations": citations, "fallback_text": NO_ANSWER_TERMINAL,
                    "ask_reason": None}
        return {"answer": "", "citations": citations, "ask_reason": "no_answer"}
    finally:
        if token is not None:
            var_child_runnable_config.reset(token)


def _route_after_answer(state: QaState) -> str:
    # 用 .get(): 1.2.11 下未写入过的键不存在于通道值中, 直接下标会 KeyError
    if state["answer"]:
        return END
    if state.get("fallback_text"):
        return END
    return "ask_user"


def build_graph(checkpointer=None):
    g = StateGraph(QaState)
    g.add_node("retrieve", _retrieve)
    g.add_node("decide", _decide)
    g.add_node("ask_user", _ask_user)
    g.add_node("answer", _answer)
    g.add_conditional_edges(START, _route_after_retrieve,
                            {"retrieve": "retrieve", "ask_user": "ask_user", END: END})
    g.add_edge("retrieve", "decide")
    g.add_edge("ask_user", "retrieve")  # resume 后回到检索全量重跑(人机交互闭环)
    g.add_conditional_edges("decide", _route_after_retrieve,
                            {"answer": "answer", "ask_user": "ask_user", END: END})
    g.add_conditional_edges("answer", _route_after_answer, {"ask_user": "ask_user", END: END})
    return g.compile(checkpointer=checkpointer or MemorySaver())


def _redis_reachable(host: str, port: int) -> bool:
    """TCP 连通性探测(1s 超时): 纯 socket, 与事件循环无关, 各环境通用"""
    import socket
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _create_checkpointer():
    """AsyncRedisSaver 优先, redis 不可用(未启动/未配置)时降级 MemorySaver

    连通性探测: 纯 TCP socket(1s 超时), 不建 redis 客户端 —— redis.asyncio
    连接绑定创建它的事件循环, 探测期建连会污染图后续驱动(Event loop is
    closed); 且死端口场景 redis-py 连接重试会放大探测耗时。连通性由探测
    覆盖, 实际读写由首次图驱动时的 aget_tuple 兜底(计划 Task 3 注意点)。
    探测通过后为图自建客户端直接构造 AsyncRedisSaver(不走 contextmanager,
    保证模块级单例存活), 连接在图的首次命令时惰性建立于图的事件循环。
    """
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    import redis.asyncio as aioredis

    config = get_config()
    try:
        if not _redis_reachable(config.redis_host, config.redis_port):
            raise RuntimeError(f"{config.redis_host}:{config.redis_port} 连接失败")
        client = aioredis.Redis(host=config.redis_host, port=config.redis_port,
                                db=config.redis_db)
        saver = AsyncRedisSaver(redis_client=client)
        logger.info(f"Redis checkpointer 就绪: {config.redis_host}:{config.redis_port}/{config.redis_db}")
        return saver
    except Exception as e:
        logger.warning(f"Redis checkpointer 不可用, 降级 MemorySaver: {e}")
        return MemorySaver()


checkpointer = _create_checkpointer()
graph = build_graph(checkpointer=checkpointer)
