"""DEV-015 记忆策略测试 - 摘要压缩"""
import pytest
from sqlalchemy import create_engine, text

from backend.core.database import migrate_memory_columns
from backend.models.messages import ChatMessage
from backend.services import memory


class MemoryLLM:
    """记录 ainvoke 输入; output 可定制"""

    def __init__(self, output="合并后的摘要内容", fail=False):
        self.calls = []
        self.output = output
        self.fail = fail

    async def ainvoke(self, messages, system_prompt=None, **kwargs):
        self.calls.append({"messages": list(messages), "system_prompt": system_prompt})
        if self.fail:
            raise RuntimeError("摘要 LLM 模拟故障")
        return self.output

    async def astream(self, messages, system_prompt=None):
        yield ""


def _make_conv(summary="旧摘要", summary_until_id="m4"):
    from backend.models.database import Conversation
    conv = Conversation(id="c1", title="t")
    conv.summary = summary
    conv.summary_until_id = summary_until_id
    return conv


def _make_msgs(n):
    from backend.models.database import Message
    return [Message(id=f"m{i}", conversation_id="c1", role="user" if i % 2 == 0 else "assistant",
                    content=f"消息{i}") for i in range(n)]


def test_conversation_has_summary_columns():
    from backend.models.database import Conversation
    assert hasattr(Conversation, "summary")
    assert hasattr(Conversation, "summary_until_id")


def test_migrate_memory_columns_adds_missing_columns(tmp_path):
    """旧库(无新列)运行迁移后补齐两列"""
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY, title VARCHAR(200))"))
        conn.commit()
    migrate_memory_columns(engine)
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(conversations)"))}
    assert {"summary", "summary_until_id"} <= cols


def test_migrate_memory_columns_idempotent(tmp_path):
    """已有列的库重复迁移不报错"""
    engine = create_engine(f"sqlite:///{tmp_path/'new.db'}")
    from backend.core.database import Base
    Base.metadata.create_all(engine)
    migrate_memory_columns(engine)
    migrate_memory_columns(engine)


@pytest.mark.asyncio
async def test_update_summary_first_compress_uses_whole_window_out():
    """无游标首次压缩: 窗口外全部消息与已有摘要进入 LLM; 游标推进"""
    llm = MemoryLLM()
    conv = _make_conv(summary=None, summary_until_id=None)
    msgs = _make_msgs(8)  # window=6: 窗口外为 m0,m1
    result = await memory.update_summary(None, conv, msgs, llm, window=6)
    assert result == "合并后的摘要内容"
    content = llm.calls[0]["messages"][0].content
    assert "用户: 消息0" in content and "助手: 消息1" in content
    assert "消息2" not in content, "窗口内消息不压缩"
    assert conv.summary_until_id == "m1"


@pytest.mark.asyncio
async def test_update_summary_incremental_only_new_window_out():
    """已有摘要 + 游标后新增窗口外消息进入 LLM; 已压缩部分不重复"""
    llm = MemoryLLM()
    conv = _make_conv(summary_until_id="m0")  # summary="旧摘要", 已压缩 m0
    msgs = _make_msgs(8)         # window=6: 窗口外 m0,m1; 游标之后仅 m1
    result = await memory.update_summary(None, conv, msgs, llm, window=6)
    assert result == "合并后的摘要内容"
    content = llm.calls[0]["messages"][0].content
    assert "旧摘要" in content
    assert "助手: 消息1" in content
    assert "消息0" not in content, "游标之前不重复压缩"
    assert conv.summary_until_id == "m1"


@pytest.mark.asyncio
async def test_update_summary_no_increment_returns_existing():
    """窗口外消息全部在游标之前 → 返回既有摘要, ainvoke 零调用"""
    llm = MemoryLLM()
    conv = _make_conv(summary_until_id="m4")
    msgs = _make_msgs(8)  # window=6: 窗口外 m0,m1 全部在游标之前
    result = await memory.update_summary(None, conv, msgs, llm, window=6)
    assert result == "旧摘要"
    assert llm.calls == [], "无增量不调用 LLM"


@pytest.mark.asyncio
async def test_update_summary_short_conversation_none():
    """消息数 ≤ 窗口 → 返回 None, 零调用"""
    llm = MemoryLLM()
    conv = _make_conv(summary=None, summary_until_id=None)
    msgs = _make_msgs(6)
    result = await memory.update_summary(None, conv, msgs, llm, window=6)
    assert result is None
    assert llm.calls == []


@pytest.mark.asyncio
async def test_update_summary_truncates_overlong_output():
    """LLM 输出超长 → 截断到 MAX_SUMMARY_CHARS"""
    llm = MemoryLLM(output="长" * 2000)
    conv = _make_conv(summary=None, summary_until_id=None)
    msgs = _make_msgs(8)
    result = await memory.update_summary(None, conv, msgs, llm, window=6)
    assert result == "长" * memory.MAX_SUMMARY_CHARS
    assert conv.summary == result


@pytest.mark.asyncio
async def test_update_summary_llm_failure_returns_none():
    """LLM 压缩失败 → 返回 None 不抛异常, 不破坏既有摘要与游标"""
    llm = MemoryLLM(fail=True)
    conv = _make_conv(summary_until_id=None)
    msgs = _make_msgs(8)
    result = await memory.update_summary(None, conv, msgs, llm, window=6)
    assert result is None
    assert conv.summary == "旧摘要", "失败不改写既有摘要"
    assert conv.summary_until_id is None, "失败不推进游标"
