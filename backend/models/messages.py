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
