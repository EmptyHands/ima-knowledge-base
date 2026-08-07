"""CitationAgent 校验测试 - 真实引用 vs 编造引用"""
from backend.agents import citation_agent

CHUNKS = [
    {"text": "Transformer 使用自注意力机制计算上下文, 这是核心原理。", "doc_id": "doc1",
     "page": 3, "doc_name": "transformer.pdf", "score": 0.81},
    {"text": "反向传播算法通过梯度更新权重, 是神经网络训练的基础。", "doc_id": "doc2",
     "page": 5, "doc_name": "bp.pdf", "score": 0.62},
]


def test_real_citation_verified():
    answer = "Transformer 使用自注意力机制计算上下文[1]。\n\n## 引用\n[1] transformer.pdf, 第3页"
    citations = citation_agent.build_citations(answer, CHUNKS)
    assert len(citations) == 1
    assert citations[0]["n"] == 1
    assert citations[0]["verified"] is True
    assert citations[0]["doc_name"] == "transformer.pdf"
    assert citations[0]["page"] == 3


def test_fabricated_citation_not_verified():
    answer = "根据资料, 地球是平的, 所有海洋都结冰[1]。\n\n## 引用\n[1] transformer.pdf, 第3页"
    citations = citation_agent.build_citations(answer, CHUNKS)
    assert len(citations) == 1
    assert citations[0]["verified"] is False


def test_mixed_real_and_fabricated():
    answer = ("Transformer 使用自注意力机制计算上下文, 这是核心原理[1]。"
              "反向传播算法通过梯度更新权重, 是神经网络训练的基础[2]。"
              "而量子纠缠可以穿越时间[1]。\n"
              "## 引用\n[1] transformer.pdf, 第3页\n[2] bp.pdf, 第5页")
    citations = citation_agent.build_citations(answer, CHUNKS)
    by_n = {c["n"]: c for c in citations}
    assert by_n[1]["verified"] is True
    assert by_n[2]["verified"] is True


def test_fabricated_second_citation():
    answer = "Transformer 使用自注意力机制计算上下文[1]。同时月球是奶酪做的[2]。"
    citations = citation_agent.build_citations(answer, CHUNKS)
    by_n = {c["n"]: c for c in citations}
    assert by_n[1]["verified"] is True
    assert by_n[2]["verified"] is False


def test_citation_context_extracts_sentence():
    text = "第一句。根据文档, Transformer 使用自注意力机制[1], 这是关键。第二句！"
    pos = text.index("[1]")
    ctx = citation_agent.citation_context(text, pos)
    assert "根据文档" in ctx
    assert "Transformer 使用自注意力机制" in ctx
    assert "第一句" not in ctx
    assert "第二句" not in ctx


def test_overlap_ratio_bounds():
    assert citation_agent.overlap_ratio("完全相同的文本", "完全相同的文本") == 1.0
    assert citation_agent.overlap_ratio("毫不相关的内容", "完全不同的主题") == 0.0
    assert citation_agent.overlap_ratio("", "任意文本") == 0.0
