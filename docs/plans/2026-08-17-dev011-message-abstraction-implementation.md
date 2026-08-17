# DEV-011 统一消息抽象 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 定义统一消息模型 ChatMessage(Pydantic)贯穿路由/agent/LLM 适配器,LLM 请求升级为结构化多轮 messages 数组。

**Architecture:** 新建 `backend/models/messages.py` 提供 `ChatMessage`(role: Literal["system","user","assistant"], content, metadata)与 `to_api_dict()`;chat 路由历史加载与反问识别改用它;answer_agent 构造 `history + 当前问题` 的 messages 列表传给 LLM;LLMProvider/LLMAdapter 接口从 `(prompt, system_prompt)` 改为 `(messages, system_prompt)`。不动数据库 schema、不改变 SSE 协议。

**Tech Stack:** Python 3.10 + FastAPI + Pydantic v2 + SQLAlchemy + pytest(asyncio)

**关联设计:** `docs/plans/2026-08-17-dev011-message-abstraction-design.md`

**测试基线:** 当前全套测试全绿(`pytest tests/ -v`,离线不耗 API)。

---

### Task 1: 消息模型 ChatMessage + 测试

**Files:**
- Create: `backend/models/messages.py`
- Create: `tests/test_messages.py`

**Step 1: 写失败测试**

`tests/test_messages.py`:

```python
"""统一消息模型 ChatMessage 测试"""
import pytest
from pydantic import ValidationError

from backend.models.messages import ChatMessage


def test_construct_valid():
    msg = ChatMessage(role="user", content="你好")
    assert msg.role == "user"
    assert msg.content == "你好"
    assert msg.metadata == {}


def test_invalid_role_raises():
    with pytest.raises(ValidationError):
        ChatMessage(role="banana", content="x")


def test_to_api_dict():
    msg = ChatMessage(role="assistant", content="回答")
    assert msg.to_api_dict() == {"role": "assistant", "content": "回答"}


def test_metadata_default_and_custom():
    m1 = ChatMessage(role="user", content="a")
    assert m1.metadata == {}
    m2 = ChatMessage(role="user", content="a", metadata={"mem": 1})
    assert m2.metadata == {"mem": 1}
```

**Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/test_messages.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.models.messages`

**Step 3: 最小实现**

`backend/models/messages.py`:

```python
"""统一消息模型 - 层间传递/LLM 请求的唯一消息载体"""
from typing import Any, Literal

from pydantic import BaseModel, Field

MessageRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: MessageRole
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_api_dict(self) -> dict:
        return {"role": self.role, "content": self.content}
```

**Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/test_messages.py -v`
Expected: 4 passed

**Step 5: 提交**

```bash
git add backend/models/messages.py tests/test_messages.py
git commit -m "feat: DEV-011 统一消息模型 - ChatMessage (Pydantic 角色/内容/元数据)"
```

---

### Task 2: answer_agent 改用 ChatMessage + 多轮 messages

**Files:**
- Modify: `backend/agents/answer_agent.py`(build_prompt:18-46、stream:49-60)
- Modify: `tests/test_answer_agent.py`(test_build_prompt_keeps_last_10_history_messages:53-57)

**Step 1: 更新测试(历史改为 ChatMessage 列表)**

`tests/test_answer_agent.py` 顶部加导入,并把 53-57 行替换:

```python
from backend.models.messages import ChatMessage

def test_build_prompt_keeps_last_10_history_messages(chunks):
    history = [ChatMessage(role="user" if i % 2 == 0 else "assistant", content=f"消息{i}")
               for i in range(15)]
    prompt = answer_agent.build_prompt("问题", history, chunks)
    assert "消息14" in prompt
    assert "消息0" not in prompt, "只保留最近 10 条历史"
```

**Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/test_answer_agent.py::test_build_prompt_keeps_last_10_history_messages -v`
Expected: FAIL — `AttributeError: 'dict' object has no attribute 'role'`(build_prompt 仍用 `msg.get`)

**Step 3: 实现**

`build_prompt` 中历史段改为属性访问:

```python
        for msg in history[-MAX_HISTORY:]:
            role = "用户" if msg.role == "user" else "助手"
            content = (msg.content or "")[:MAX_HISTORY_CHARS]
            lines.append(f"{role}: {content}")
```

参数类型注释改为 `history: list[ChatMessage]`(顶部 `from backend.models.messages import ChatMessage`)。

`stream` 中构造多轮 messages 并传给 LLM(替换 54-56 行的 prompt 构造与调用):

```python
    llm = llm or get_llm()
    messages = [*history, ChatMessage(role="user", content=question)]
    answer_parts = []
    async for token in llm.astream(messages, system_prompt=SYSTEM_PROMPT):
```

此时 llm 接口仍是 `(prompt, system_prompt)`,FakeLLM 用位置参数接收列表,行为不变,测试应绿。

**Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/test_answer_agent.py -v`
Expected: 全绿

**Step 5: 提交**

```bash
git add backend/agents/answer_agent.py tests/test_answer_agent.py
git commit -m "feat: DEV-011 answer_agent 历史/请求改走 ChatMessage 多轮 messages"
```

---

### Task 3: LLM 适配器接口升级 + 同步全部 FakeLLM

**Files:**
- Modify: `backend/core/llm_adapter.py`(LLMProvider:12-22、LLMAdapter.ainvoke:47-52、astream:73-78、invoke_sync:101-108)
- Modify: `tests/conftest.py`(FakeLLM:56-65)
- Modify: `tests/test_answer_agent.py`(FakeLLM:7-10)
- Modify: `tests/test_chat_stream.py`(FailingLLM:89-94、WebLLM:116-122)
- Modify: `tests/test_e2e_flow.py`(E2EFakeLLM:16-22)
- Modify: `tests/test_fallback.py`(EmptyLLM:182-188)

**Step 1: 改抽象与实现签名(先改,测试随后同步)**

`LLMProvider`:

```python
    @abstractmethod
    async def ainvoke(self, messages: list, system_prompt: str = None, **kwargs) -> str:
        ...

    @abstractmethod
    async def astream(self, messages: list, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        ...
```

新增模块级助手函数:

```python
def _build_api_messages(messages: list, system_prompt: str = None) -> list[dict]:
    """ChatMessage 列表 → OpenAI 请求消息体; system_prompt 插为第一条"""
    out = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})
    out.extend(m.to_api_dict() for m in messages)
    return out
```

`LLMAdapter.ainvoke`:

```python
    async def ainvoke(self, messages, system_prompt=None, **kwargs) -> str:
        return await self._chat(_build_api_messages(messages, system_prompt), **kwargs)
```

`LLMAdapter.astream`:

```python
    async def astream(self, messages, system_prompt=None, **kwargs) -> AsyncGenerator[str, None]:
        api_messages = _build_api_messages(messages, system_prompt)
        try:
            stream = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model_name,
                    messages=api_messages,
                    temperature=kwargs.get("temperature", self.temperature),
                    max_tokens=kwargs.get("max_tokens", self.max_tokens or 8000),
                    stream=True,
                ),
                timeout=self.timeout,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        except asyncio.TimeoutError:
            logger.error("LLM stream timeout")
            raise
        except Exception as e:
            logger.error(f"LLM stream failed: {e}")
            raise
```

`invoke_sync`:

```python
    def invoke_sync(self, messages, system_prompt=None, **kwargs) -> str:
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_running_loop()
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.ainvoke(messages, system_prompt, **kwargs))
```

**Step 2: 同步全部 FakeLLM 签名(`prompt` → `messages`)**

所有 `async def astream(self, prompt, system_prompt=None)` → `async def astream(self, messages, system_prompt=None)`;`ainvoke` 同理。涉及文件:conftest.py:56/62、test_answer_agent.py:8、test_chat_stream.py:90/93/117/121、test_e2e_flow.py:17/21、test_fallback.py:183/187。

注意 test_chat_stream.py 的 `WebLLM.ainvoke`(121-122)引用了 `self._tokens`(未定义,该路径未被调用)——只改参数名,不动逻辑。

**Step 3: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 全套通过(全部走 FakeLLM,不触发真实 LLMAdapter)

**Step 4: 提交**

```bash
git add backend/core/llm_adapter.py tests/conftest.py tests/test_answer_agent.py tests/test_chat_stream.py tests/test_e2e_flow.py tests/test_fallback.py
git commit -m "feat: DEV-011 LLM 适配器接口升级为多轮 messages 数组"
```

---

### Task 4: chat 路由历史加载与反问识别改 ChatMessage

**Files:**
- Modify: `backend/api/routes/chat.py`(import:11、_confirm_question:30-38、历史加载:123-125)

**Step 1: 实现**

顶部导入:

```python
from backend.models.messages import ChatMessage
```

`_confirm_question` 改为属性访问:

```python
def _confirm_question(history: list[ChatMessage], question: str) -> tuple[str, bool]:
    """反问确认识别: 最近助手消息是反问模板且本次回复为确认词时, 返回(原问题, True)"""
    q = question.strip().strip("。.!！?？ ")
    last_assistant = next((m for m in reversed(history) if m.role == "assistant"), None)
    if last_assistant:
        m = _RE_FALLBACK_QUESTION.search(last_assistant.content or "")
        if m and q in CONFIRM_WORDS:
            return m.group(1), True
    return question, False
```

历史加载(123-125 行):

```python
    history_rows = db.query(Message).filter(Message.conversation_id == conv_id) \
        .order_by(Message.created_at.desc()).limit(HISTORY_LIMIT).all()
    history = [ChatMessage(role=m.role, content=m.content) for m in reversed(history_rows)]
```

**Step 2: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/test_chat_stream.py tests/test_fallback.py tests/test_e2e_flow.py -q`
Expected: 全绿(反问确认闭环、SSE 事件序列、e2e 全链路不受影响)

**Step 3: 提交**

```bash
git add backend/api/routes/chat.py
git commit -m "feat: DEV-011 chat 路由历史/反问识别改走 ChatMessage"
```

---

### Task 5: 全量回归 + README 版本记录

**Files:**
- Modify: `README.md`(版本变更记录表顶行)

**Step 1: 全量回归**

Run: `venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全套全绿(消息模型 4 个新测试 + 既有 117 个)

**Step 2: README 版本记录**

版本变更记录表顶部插入:

```markdown
| v1.3.0 | 2026-08-17 | 新增 DEV-011:统一消息抽象 — Pydantic ChatMessage(角色/内容/元数据)贯穿路由/answer_agent/LLM 适配器,LLM 请求升级为结构化多轮 messages |
```

**Step 3: 提交**

```bash
git add README.md
git commit -m "docs: DEV-011 README 记录 (v1.3.0)"
```

**Step 4: 手工验证(可选,需真实 LLM)**

多轮对话:第一轮提问 → 助手回答 → 第二轮追问(引用第一轮内容),确认回答能基于历史(结构化多轮已生效,历史不再拼进 prompt 文本)。

---

## 验收清单

- [ ] `pytest tests/ -v` 全绿(含新增 4 个消息模型测试)
- [ ] 全仓库无 `llm.astream(prompt` / `ainvoke(prompt` 残留调用(除文档)
- [ ] chat 路由历史为 `list[ChatMessage]`,反问识别用属性访问
- [ ] LLM 请求体首条为 system(若有 system_prompt),其后为各 ChatMessage 的 to_api_dict
- [ ] README 版本记录 v1.3.0
