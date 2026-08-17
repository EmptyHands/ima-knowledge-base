"""AnswerAgent / CitationAgent 测试 - 伪 LLM 注入, 不依赖网络"""
import pytest

from backend.agents import answer_agent, citation_agent
from backend.models.messages import ChatMessage


class FakeLLM:
    async def astream(self, messages, system_prompt=None):
        for token in ["基于", "片段", "[1]", "的", "回答", "\n## 引用\n", "[1] transformer.pdf, 第3页"]:
            yield token


class CapturingLLM:
    """记录 astream 收到的 messages, 用于断言 LLM 请求内容 (DEV-018)"""

    def __init__(self):
        self.messages = None

    async def astream(self, messages, system_prompt=None):
        self.messages = list(messages)
        for token in ["回答", "[1]"]:
            yield token


@pytest.fixture
def chunks():
    return [
        {"text": "Transformer 使用自注意力机制计算上下文, 这是核心原理。", "doc_id": "doc1",
         "page": 3, "doc_name": "transformer.pdf", "score": 0.81},
        {"text": "反向传播算法通过梯度更新权重。", "doc_id": "doc2",
         "page": 5, "doc_name": "bp.pdf", "score": 0.62},
    ]


def test_build_prompt_numbers_and_truncates_chunks(chunks):
    prompt = answer_agent.build_prompt("Transformer 是什么", [], chunks)
    assert "[1]" in prompt and "[2]" in prompt
    assert "transformer.pdf 第3页" in prompt
    assert "bp.pdf 第5页" in prompt
    assert "问题: Transformer 是什么" in prompt


def test_build_prompt_web_results_numbering_continues_after_chunks(chunks):
    """DEV-018: 网络结果编号延续片段之后, [n] 全局唯一, 与引用映射规则一致"""
    web = [
        {"title": "T1", "url": "https://a.com", "snippet": "s1"},
        {"title": "T2", "url": "https://b.com", "snippet": "s2"},
    ]
    prompt = answer_agent.build_prompt("问题", [], chunks, web)
    assert "[3]" in prompt and "[4]" in prompt
    assert "[1]" not in prompt.split("网络搜索结果:")[1], "网络结果不应重复从 1 编号"
    assert "https://a.com" in prompt


@pytest.mark.asyncio
async def test_stream_citations_include_web_results(chunks):
    """DEV-018: stream 的 citations 事件应包含网络结果映射的引用"""
    web = [{"title": "T1", "url": "https://a.com", "snippet": "s1"}]
    events = [e async for e in answer_agent.stream("问题", [], chunks, web, llm=FakeLLM())]
    citations = events[-1]["data"]
    assert citations[0]["doc_name"] == "transformer.pdf"
    assert citations[0]["page"] == 3


def test_build_prompt_keeps_last_10_history_messages(chunks):
    history = [ChatMessage(role="user" if i % 2 == 0 else "assistant", content=f"消息{i}")
               for i in range(15)]
    prompt = answer_agent.build_prompt("问题", history, chunks)
    assert "消息14" in prompt
    assert "消息0" not in prompt, "只保留最近 10 条历史"


def test_build_prompt_truncates_long_chunk():
    chunk = [{"text": "长" * 2000, "doc_id": "d", "page": 1, "doc_name": "text.pdf", "score": 0.5}]
    prompt = answer_agent.build_prompt("问题", [], chunk)
    assert len("长" * 2000) > answer_agent.MAX_CHUNK_CHARS
    assert prompt.count("长") == answer_agent.MAX_CHUNK_CHARS


def test_parse_citation_numbers_dedupe_and_order():
    nums = citation_agent.parse_citation_numbers("结论[2][1], 补充[2] 与 [3] 引用")
    assert nums == [2, 1, 3]


def test_build_citations_maps_numbers_to_chunks(chunks):
    answer = "Transformer 使用自注意力机制计算上下文[1]。反向传播算法通过梯度更新权重[2]。"
    citations = citation_agent.build_citations(answer, chunks)
    assert len(citations) == 2
    assert citations[0]["n"] == 1
    assert citations[0]["doc_name"] == "transformer.pdf"
    assert citations[0]["page"] == 3
    assert citations[0]["verified"] is True
    assert citations[1]["doc_name"] == "bp.pdf"
    assert citations[1]["verified"] is True


def test_build_citations_skips_out_of_range(chunks):
    citations = citation_agent.build_citations("答案[9]越界", chunks)
    assert citations == []


@pytest.mark.asyncio
async def test_stream_passes_chunks_and_web_to_llm(chunks):
    """DEV-018: LLM 请求必须携带检索片段与网络结果, 而非仅裸问题"""
    web = [{"title": "T1", "url": "https://a.com", "snippet": "s1"}]
    history = [ChatMessage(role="user", content="上一轮问题"),
               ChatMessage(role="assistant", content="上一轮回答")]
    llm = CapturingLLM()
    events = [e async for e in answer_agent.stream("最新问题", history, chunks, web, llm=llm)]
    assert events

    assert llm.messages is not None
    assert [m.role for m in llm.messages] == ["user", "assistant", "user"], "历史保持独立消息"
    content = llm.messages[-1].content
    assert "Transformer 使用自注意力机制计算上下文" in content, "检索片段必须进入 LLM 请求"
    assert "https://a.com" in content, "网络结果必须进入 LLM 请求"
    assert "问题: 最新问题" in content
    assert "上一轮问题" not in content, "历史以独立消息传入, 不应在用户消息内重复"


@pytest.mark.asyncio
async def test_stream_event_sequence(chunks):
    events = [e async for e in answer_agent.stream("Transformer 是什么", [], chunks, llm=FakeLLM())]
    types = [e["type"] for e in events]
    assert types[0] == "status"
    assert types[-1] == "citations"
    assert all(t == "chunk" for t in types[1:-1])
    assert "".join(e["data"] for e in events if e["type"] == "chunk") == (
        "基于片段[1]的回答\n## 引用\n[1] transformer.pdf, 第3页"
    )
    citations = events[-1]["data"]
    assert citations[0]["doc_name"] == "transformer.pdf"
    assert citations[0]["page"] == 3


@pytest.mark.asyncio
async def test_stream_injects_summary_as_system_message(chunks):
    """DEV-015: 传 summary 时, LLM 请求首条为 system 摘要消息, 历史仍独立, 检索内容在用户消息"""
    history = [ChatMessage(role="user", content="上一轮问题"),
               ChatMessage(role="assistant", content="上一轮回答")]
    llm = CapturingLLM()
    events = [e async for e in answer_agent.stream(
        "最新问题", history, chunks, [], llm=llm, summary="用户需要跟踪每日价格")]
    assert events
    assert llm.messages[0].role == "system"
    assert "用户需要跟踪每日价格" in llm.messages[0].content
    assert [m.role for m in llm.messages[1:]] == ["user", "assistant", "user"]
    assert "Transformer 使用自注意力机制计算上下文" in llm.messages[-1].content


@pytest.mark.asyncio
async def test_stream_without_summary_keeps_message_structure(chunks):
    """DEV-015 回归: 不传 summary 时消息结构不变"""
    history = [ChatMessage(role="user", content="上轮"), ChatMessage(role="assistant", content="上答")]
    llm = CapturingLLM()
    [e async for e in answer_agent.stream("问题", history, chunks, [], llm=llm)]
    assert [m.role for m in llm.messages] == ["user", "assistant", "user"]
