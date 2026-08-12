"""CitationAgent - 引用解析与校验: [n] 上下文与检索片段的重叠率阈值校验"""
import re

CITATION_PATTERN = re.compile(r"\[(\d+)\]")
SNIPPET_CHARS = 200
VERIFY_THRESHOLD = 0.6
_SENTENCE_SEPS = "。！？；\n"


def parse_citation_numbers(answer_text: str) -> list[int]:
    """从回答文本解析 [n] 引用编号, 保序去重"""
    nums = []
    seen = set()
    for m in CITATION_PATTERN.finditer(answer_text):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            nums.append(n)
    return nums


MIN_SEGMENT_CHARS = 20
MAX_CONTEXT_CHARS = 150


def citation_context(answer_text: str, pos: int) -> str:
    """取 [n] 之前的引用上下文: 从句子起点或上一个 [n] 之后到当前 [n]

    一句话引用多个片段时按 [n] 分段, 各段独立校验, 避免上下文被其他来源内容稀释;
    [n] 紧跟在标点后(如 "…避免。[1]")时片段为空, 向前回溯补齐到 MIN_SEGMENT_CHARS
    """
    start = max((answer_text.rfind(ch, 0, pos) for ch in _SENTENCE_SEPS), default=-1) + 1
    for m in CITATION_PATTERN.finditer(answer_text, 0, pos):
        start = max(start, m.end())
    while pos - start < MIN_SEGMENT_CHARS:
        search_end = start - 1
        crossed = search_end >= 0 and answer_text[search_end] in _SENTENCE_SEPS
        if crossed:
            search_end -= 1  # [n] 紧跟在标点后时, 越过该标点取标点前的内容
        prev_boundary = max(
            (answer_text.rfind(ch, 0, search_end + 1) for ch in _SENTENCE_SEPS),
            default=-1,
        )
        for m in CITATION_PATTERN.finditer(answer_text, 0, search_end + 1):
            prev_boundary = max(prev_boundary, m.end())
        if crossed and prev_boundary < 0:
            start = 0  # 无更早边界, 直接取到句子开头
            break
        if prev_boundary < 0:
            break
        new_start = prev_boundary + 1
        if new_start >= start:
            break  # 边界无法前移(上一引用段与当前段相邻), 接受当前短上下文, 避免死循环
        start = new_start
    ctx = answer_text[start:pos].strip(" .,;:!?，。；：！？、\n\t")
    return ctx[-MAX_CONTEXT_CHARS:]


MIN_CONTEXT_CHARS = 8


def containment_ratio(context: str, chunk_text: str) -> float:
    """上下文二元组在 chunk 中的占比 |a∩b|/|a|, 判断引用句是否有原文依据

    用 Jaccard 时分母被长 chunk 主导, 长文档中逐字引用也得不到高分; 包含率与
    chunk 长度无关, 引用句越贴近 chunk 原文越接近 1.0
    """
    a = _char_bigrams(context)
    b = _char_bigrams(chunk_text)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def _char_bigrams(text: str) -> set[str]:
    text = re.sub(r"\s+", "", text)
    return {text[i:i + 2] for i in range(max(0, len(text) - 1))}


def build_citations(answer_text: str, chunks: list[dict]) -> list[dict]:
    """按回答中的 [n] 映射检索片段并校验, 返回 [{n, doc_name, page, snippet, verified}]

    首次出现的编号优先处理(引用列表中的重复编号不再重复校验);
    低于阈值 0.6 的引用标记 verified=false, 前端灰显"该结论无直接引用来源"
    """
    citations = []
    seen = set()
    for m in CITATION_PATTERN.finditer(answer_text):
        n = int(m.group(1))
        if n in seen:
            continue
        seen.add(n)
        chunk = chunks[n - 1] if 0 <= n - 1 < len(chunks) else None
        if chunk is None:
            continue
        chunk_text = chunk.get("text", "")
        context = citation_context(answer_text, m.start())
        # 上下文过短时常见二元组易与 chunk 巧合重叠, 不足以下"有原文依据"的结论
        verified = len(context) >= MIN_CONTEXT_CHARS and \
            containment_ratio(context, chunk_text) >= VERIFY_THRESHOLD
        citations.append({
            "n": n,
            "doc_name": chunk.get("doc_name", ""),
            "page": chunk.get("page", 0),
            "snippet": chunk_text[:SNIPPET_CHARS],
            "verified": verified,
        })
    return citations
