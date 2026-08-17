"""CitationAgent 校验测试 - 真实引用 vs 编造引用"""
from backend.agents import citation_agent

CHUNKS = [
    {"text": "Transformer 使用自注意力机制计算上下文, 这是核心原理。", "doc_id": "doc1",
     "page": 3, "doc_name": "transformer.pdf", "score": 0.81},
    {"text": "反向传播算法通过梯度更新权重, 是神经网络训练的基础。", "doc_id": "doc2",
     "page": 5, "doc_name": "bp.pdf", "score": 0.62},
]

WEB_RESULTS = [
    {"title": "Transformer 架构详解", "url": "https://example.com/transformer",
     "snippet": "Transformer 使用自注意力机制计算上下文, 这是核心原理。"},
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


def test_citation_context_segments_multi_citation_sentence():
    """一句话引用两个片段时, 上下文按 [n] 分段, 互不稀释"""
    text = "Transformer 使用自注意力机制计算上下文[1], 反向传播通过梯度更新权重[2]。"
    ctx1 = citation_agent.citation_context(text, text.index("[1]"))
    ctx2 = citation_agent.citation_context(text, text.index("[2]"))
    assert "Transformer" in ctx1 and "反向传播" not in ctx1
    assert "反向传播" in ctx2 and "Transformer" not in ctx2


def test_citation_context_backtracks_when_marker_after_punctuation():
    """[n] 紧跟句号后(如 "…避免。[1]")时上下文为空, 应回溯到上一句"""
    text = "第一点完全无关的铺垫, 然后经验可以复用, 记住曾犯的错误, 下次就能避免。[1]"
    ctx = citation_agent.citation_context(text, text.index("[1]"))
    assert "避免" in ctx
    assert len(ctx) >= citation_agent.MIN_SEGMENT_CHARS


def test_citation_after_period_verified():
    """回归: 真实 LLM 常在句号后标注 [n], 回溯后应能校验引用"""
    chunk_text = "经验可以复用, 记住曾犯的错误, 下次就能避免。大模型本身没有记忆, 每次对话从零开始。"
    chunk = {"text": chunk_text, "doc_id": "doc1", "page": 1, "doc_name": "agent_memory.txt", "score": 0.8}
    answer = "经验可以复用, 记住曾犯的错误, 下次就能避免。[1]"
    citations = citation_agent.build_citations(answer, [chunk])
    assert citations[0]["verified"] is True


def test_citation_context_meta_commentary_short_context_not_verified():
    """元评论式回答(如"知识库中片段[1]为标题")上下文过短, 不应被判为有原文依据"""
    chunk = {"text": "第一部分 为什么 Agent 需要记忆", "doc_id": "doc1", "page": 9,
             "doc_name": "agent_memory.txt", "score": 0.89}
    answer = "知识库中片段[1]为标题“第一部分 为什么 Agent 需要记忆”, 但未提供具体说明。"
    citations = citation_agent.build_citations(answer, [chunk])
    assert citations[0]["verified"] is False


def test_containment_ratio_bounds():
    assert citation_agent.containment_ratio("完全相同的文本", "完全相同的文本") == 1.0
    assert citation_agent.containment_ratio("毫不相关的内容", "完全不同的主题") == 0.0
    assert citation_agent.containment_ratio("", "任意文本") == 0.0


def test_containment_ratio_robust_to_chunk_length():
    """DEV-002 回归: Jaccard 时逐字引用会被长 chunk 稀释到 0.05, 包含率应保持 1.0"""
    chunk = ("这是第一句完全没有用的铺垫内容, " * 30) + "本产品支持七天内无理由退换货。"
    quote = "本产品支持七天内无理由退换货。"
    assert citation_agent.containment_ratio(quote, chunk) == 1.0


def test_long_chunk_verbatim_quote_verified():
    """DEV-002 回归: 800 字 chunk 中逐字引用 40 字原文必须 verified=True"""
    filler = " ".join(f"第{i}条无关的背景资料, 具体条款说明如下, 敬请用户参考并确认。" for i in range(15))
    chunk_text = filler + "本产品支持七天内无理由退换货, 超过七天按折旧价格退款, 运费由买家承担。"
    chunk = {"text": chunk_text, "doc_id": "doc1", "page": 2, "doc_name": "policy.pdf", "score": 0.75}
    answer = "本产品支持七天内无理由退换货, 超过七天按折旧价格退款, 运费由买家承担[1]。\n## 引用\n[1] policy.pdf, 第2页"
    citations = citation_agent.build_citations(answer, [chunk])
    assert len(citations) == 1
    assert citations[0]["verified"] is True


def test_fabricated_citation_in_long_chunk_not_verified():
    chunk_text = " ".join(f"第{i}条无关的背景资料, 具体条款说明如下, 敬请用户参考并确认。" for i in range(15))
    chunk = {"text": chunk_text, "doc_id": "doc1", "page": 2, "doc_name": "policy.pdf", "score": 0.75}
    answer = "地球是平的, 所有海洋都结冰, 太阳围绕月亮旋转, 猫会说话[1]。"
    citations = citation_agent.build_citations(answer, [chunk])
    assert citations[0]["verified"] is False


def test_short_context_not_verified_by_coincidence():
    """过短上下文(如"是[1]")不应因常见二元组巧合而被判定有原文依据"""
    chunk = {"text": "这是核心原理, 请仔细理解。", "doc_id": "doc1", "page": 1,
             "doc_name": "t.pdf", "score": 0.5}
    answer = "是[1]。"
    citations = citation_agent.build_citations(answer, [chunk])
    assert citations[0]["verified"] is False


def test_doc_level_citation_still_carries_source_metadata():
    """DEV-007: 降级引用(verified=False)仍须携带 doc_name/page, 供前端文档级展示"""
    chunk = {"text": "这是核心原理, 请仔细理解。", "doc_id": "doc1", "page": 7,
             "doc_name": "guide.pdf", "score": 0.5}
    answer = "根据我自己的经验, 直接回答这个问题[1]。"
    citations = citation_agent.build_citations(answer, [chunk])
    assert len(citations) == 1
    c = citations[0]
    assert c["verified"] is False
    assert c["doc_name"] == "guide.pdf"
    assert c["page"] == 7


def test_web_citation_maps_to_web_results():
    """DEV-018: 无片段纯联网回答, [n] 应映射到网络结果并可点击跳转"""
    answer = "根据网络资料, Transformer 使用自注意力机制计算上下文[1]。"
    citations = citation_agent.build_citations(answer, [], WEB_RESULTS)
    assert len(citations) == 1
    c = citations[0]
    assert c["n"] == 1
    assert c["doc_name"] == "Transformer 架构详解"
    assert c["url"] == "https://example.com/transformer"
    assert c["verified"] is True


def test_web_citation_numbering_continues_after_chunks():
    """DEV-018: 片段与网络结果并存时, 网络结果编号延续片段之后"""
    answer = "Transformer 使用自注意力机制计算上下文[1]。自注意力机制是核心[3]。"
    citations = citation_agent.build_citations(answer, CHUNKS, WEB_RESULTS)
    by_n = {c["n"]: c for c in citations}
    assert by_n[1]["doc_name"] == "transformer.pdf"
    assert "url" not in by_n[1]
    assert by_n[3]["doc_name"] == "Transformer 架构详解"
    assert by_n[3]["url"] == "https://example.com/transformer"


def test_web_citation_out_of_range_skipped():
    citations = citation_agent.build_citations("答案[2]", [], WEB_RESULTS)
    assert citations == []


def test_web_citation_not_affected_by_chunk_verification():
    """DEV-018: 网络引用恒 verified(来源可直接跳转自证), 与片段包含率校验无关"""
    answer = "完全改写的说法, 与摘要不一致[1]。"
    citations = citation_agent.build_citations(answer, [], WEB_RESULTS)
    assert len(citations) == 1
    assert citations[0]["verified"] is True
