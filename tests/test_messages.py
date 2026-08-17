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
