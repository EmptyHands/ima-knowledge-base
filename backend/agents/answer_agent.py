"""AnswerAgent - 流式回答生成, 遵守引用标注规则"""
from typing import AsyncGenerator, Optional

from backend.agents.citation_agent import build_citations
from backend.core.llm_adapter import get_llm
from backend.models.messages import ChatMessage

SYSTEM_PROMPT = """你基于以下检索片段和网络搜索结果回答问题。规则:
1. 回答内容来自某片段或网络结果时,在引用内容最后一个字后面、句号之前标注 [n](n 为该来源的编号);一句话引用多个来源时,在各自内容处分别标注
2. 无依据的部分明确说明"知识库中未找到相关依据"
3. 回答末尾输出"## 引用"列表: 知识库来源为 [n] 文档名, 第x页; 网络来源为 [n] 标题 (网址)
4. 不要编造片段中不存在的内容"""

MAX_CHUNK_CHARS = 800
MAX_HISTORY = 10
MAX_HISTORY_CHARS = 500


def build_prompt(question: str, history: list[ChatMessage], chunks: list[dict],
                 web_results: Optional[list[dict]] = None,
                 include_history: bool = True) -> str:
    """构造提示词: 最近 10 条消息 + 检索片段(截断 800 字, 附编号)

    include_history=False 时历史由调用方以独立消息传入, 避免重复
    """
    parts = []
    if include_history and history:
        lines = []
        for msg in history[-MAX_HISTORY:]:
            role = "用户" if msg.role == "user" else "助手"
            content = (msg.content or "")[:MAX_HISTORY_CHARS]
            lines.append(f"{role}: {content}")
        parts.append("历史对话:\n" + "\n".join(lines))
    if chunks:
        lines = []
        for i, c in enumerate(chunks, 1):
            text = (c.get("text") or "")[:MAX_CHUNK_CHARS]
            lines.append(f"[{i}] {text}\n    来源: {c.get('doc_name', '')} 第{c.get('page', '?')}页")
        parts.append("检索片段:\n" + "\n".join(lines))
    # 网络结果延续片段编号, 保证 [n] 全局唯一, 与 build_citations 映射规则一致
    base = len(chunks)
    for i, w in enumerate(web_results or [], 1):
        lines = [
            f"[{base + i}] {w.get('title', '')}",
            f"    {w.get('snippet', '')}",
            f"    来源: {w.get('url', '')}",
        ]
        parts.append("网络搜索结果:\n" + "\n".join(lines))
    parts.append(f"问题: {question}")
    parts.append("请严格按照引用规则回答。")
    return "\n\n".join(parts)


async def stream(question: str, history: list[ChatMessage], chunks: list[dict],
                 web_results: Optional[list[dict]] = None, llm=None) -> AsyncGenerator[dict, None]:
    """流式回答: 依次 yield {"type": "status"} → {"type": "chunk", "data": token} → {"type": "citations", "data": [...]}"""
    yield {"type": "status", "data": "检索完成, 正在生成回答"}
    llm = llm or get_llm()
    # 检索片段与网络结果随最后一条用户消息进入 LLM 请求, 历史保持独立消息(DEV-018)
    content = build_prompt(question, history, chunks, web_results or [], include_history=False)
    messages = [*history, ChatMessage(role="user", content=content)]
    answer_parts = []
    async for token in llm.astream(messages, system_prompt=SYSTEM_PROMPT):
        answer_parts.append(token)
        yield {"type": "chunk", "data": token}
    citations = build_citations("".join(answer_parts), chunks, web_results or [])
    yield {"type": "citations", "data": citations}
