"""记忆服务 - 对话摘要压缩 (DEV-015): 窗口外历史经 LLM 增量压缩, 注入后续回答"""
import logging
from typing import Optional

from backend.models.database import Conversation
from backend.models.messages import ChatMessage

logger = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 800
MAX_HISTORY_CHARS = 500

SUMMARY_SYSTEM_PROMPT = """你是对话记忆整理助手。根据已有摘要和新增对话消息, 生成更新后的对话摘要。要求:
1. 保留用户的关键事实、偏好与要求
2. 保留跨轮承诺与阶段性结论
3. 新信息与旧摘要合并, 去除已过时内容
4. 无新信息时保留原摘要
5. 输出不超过 800 字"""


def _window_out_new(all_messages, window, summary_until_id) -> list:
    """窗口外且在游标之后的消息(增量): 全量消息中窗口前的部分, 再按游标过滤"""
    window_out = all_messages[:-window] if len(all_messages) > window else []
    if summary_until_id:
        window_out = [m for m in window_out if m.id > summary_until_id]
    return window_out


async def update_summary(db, conv: Conversation, all_messages: list, llm, window: int) -> Optional[str]:
    """窗口外历史增量压缩为对话摘要; 返回最新摘要(可注入), 失败返回 None 不影响问答

    - 无增量: 返回既有摘要(照常注入)
    - LLM 失败: 返回 None(本轮不注入), 下次再试
    """
    try:
        to_compress = _window_out_new(all_messages, window, conv.summary_until_id)
        if not to_compress:
            return conv.summary
        lines = []
        if conv.summary:
            lines.append(f"已有摘要:\n{conv.summary}")
        for m in to_compress:
            role = "用户" if m.role == "user" else "助手"
            lines.append(f"{role}: {(m.content or '')[:MAX_HISTORY_CHARS]}")
        summary = await llm.ainvoke(
            [ChatMessage(role="user", content="\n".join(lines))],
            system_prompt=SUMMARY_SYSTEM_PROMPT,
        )
        conv.summary = (summary or "").strip()[:MAX_SUMMARY_CHARS]
        conv.summary_until_id = to_compress[-1].id
        if db is not None:
            db.commit()
        return conv.summary
    except Exception as e:
        logger.warning(f"摘要压缩失败(不影响问答): {e}")
        return None
