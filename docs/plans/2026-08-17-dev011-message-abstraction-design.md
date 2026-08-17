# DEV-011 统一消息抽象设计

**日期**:2026-08-17
**状态**:已批准
**关联条目**:DEV-011 消息格式缺乏统一抽象

## 背景与问题

对话历史、提示词、LLM 请求的消息均以普通字典/字符串在层间传递,没有统一的「消息」类型定义:

| 层 | 形态 | 位置 |
|---|---|---|
| 数据库 | `Message` ORM 模型(role/content/citations_json) | `backend/models/database.py:74` |
| 路由层 | 历史转裸 dict `[{"role": ..., "content": ...}]` | `chat.py:125` |
| 反问识别 | `_confirm_question(history)` 用 `m["role"]`/`m["content"]` | `chat.py:30` |
| 提示词构造 | `build_prompt(question, history, chunks, ...)` 逐个 dict 拼文本 | `answer_agent.py:18` |
| LLM 适配器 | 只接受 `prompt` 字符串,内部拼两个 dict 发请求 | `llm_adapter.py` |

影响:类型弱约束(传错 role/字段不报错);多轮历史靠手工拼进 prompt 文本,LLM 侧无法获得结构化多轮对话;后续引入工具调用、记忆策略、langgraph 状态时,消息结构变更将波及所有层。

## 设计目标

1. 定义统一消息模型(角色/内容/可选元数据),作为层间传递的统一载体
2. LLM 适配器升级为接收结构化 `messages` 数组(原生多轮请求)
3. 不改数据库 schema、不改变 SSE 协议
4. 非法消息值在构造时立即失败(根治"弱约束")

## 方案对比

| 维度 | A dataclass + 枚举 | B Pydantic BaseModel(选定) |
|---|---|---|
| 校验 | ✗ 无,弱约束未根治 | ✓ 非法 role 立即抛 ValidationError |
| 序列化 | 手写 to_dict | model_dump 免费 |
| 新依赖 | 无 | 无(fastapi 已带 pydantic v2) |
| 生态一致性 | 与 FastAPI 分离 | 一致(API 层已有 Pydantic 先例) |
| 可扩展性 | 字段易加、校验需自管 | 字段+校验+序列化自动跟上 |

选 B:DEV-011 的痛点正是"无类型约束",Pydantic 在校验、序列化、生态一致性上全面对齐,零新增依赖,改动量与 dataclass 相当。

## 设计细节

### 1. 消息模型(新文件 `backend/models/messages.py`)

```python
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

- `Literal` 而非 Enum:数据库/前端/OpenAI API 均为字符串,Literal 直接兼容且校验生效
- `metadata`:扩展位(记忆策略/工具调用落地用),默认空 dict
- `to_api_dict()`:唯一的"转 OpenAI 请求体"出口

### 2. LLM 适配器接口升级(`backend/core/llm_adapter.py`)

`LLMProvider` 抽象与 `LLMAdapter` 实现同步改:

```
ainvoke(messages: list[ChatMessage], system_prompt=None, **kwargs) -> str
astream(messages: list[ChatMessage], system_prompt=None, **kwargs) -> AsyncGenerator[str, None]
```

- system_prompt 存在时插为第一条 system 消息,其余 `to_api_dict()` 展平
- `invoke_sync` 签名同步保持一致

### 3. 路由与 agent 层

- `chat.py:125` 历史加载:`[ChatMessage(role=m.role, content=m.content) for m in ...]`,DB 字符串进模型自动校验
- `chat.py:30` `_confirm_question(history: list[ChatMessage])`:属性访问 `msg.role == "assistant"`、`msg.content`
- `answer_agent.py` `build_prompt(question, history: list[ChatMessage], ...)`:属性访问
- `answer_agent.py` `stream(...)`:构造 `messages = history + [ChatMessage(role="user", content=question)]`,调 `llm.astream(messages, system_prompt=SYSTEM_PROMPT)`

### 4. 测试

- 5 处 FakeLLM 签名更新(conftest.py、test_answer_agent.py、test_chat_stream.py ×2、test_e2e_flow.py、test_fallback.py)
- 新增消息模型测试:合法构造、非法 role 抛 ValidationError、to_api_dict 输出、metadata 默认空
- 全套离线测试跑绿(不消耗 API 费用)

### 5. 错误处理

Pydantic ValidationError 在消息构造处自然 fail-fast。层间为受控代码而非用户输入边界,不额外捕获。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `backend/models/messages.py` | 新增:ChatMessage + MessageRole |
| `backend/core/llm_adapter.py` | 接口改 messages 数组 |
| `backend/api/routes/chat.py` | 历史加载/反问识别改 ChatMessage |
| `backend/agents/answer_agent.py` | build_prompt/stream 改 ChatMessage + 多轮 messages |
| `tests/*` | 5 处 FakeLLM 签名 + 新增消息模型测试 |

## 验证方式

1. `pytest tests/ -v` 全绿
2. 手工:多轮对话后提问,确认 LLM 能基于历史回答(结构化多轮生效)
