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


def citation_context(answer_text: str, pos: int) -> str:
    """取 [n] 所在句子(按中英文句末标点/换行切分)作为引用上下文"""
    start = max((answer_text.rfind(ch, 0, pos) for ch in _SENTENCE_SEPS), default=-1) + 1
    end = len(answer_text)
    for i in range(pos, len(answer_text)):
        if answer_text[i] in _SENTENCE_SEPS:
            end = i + 1
            break
    return answer_text[start:end].strip()


def overlap_ratio(context: str, chunk_text: str) -> float:
    """字符二元组 Jaccard 相似度, 用于判断引用是否有原文依据"""
    a = _char_bigrams(context)
    b = _char_bigrams(chunk_text)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


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
        citations.append({
            "n": n,
            "doc_name": chunk.get("doc_name", ""),
            "page": chunk.get("page", 0),
            "snippet": chunk_text[:SNIPPET_CHARS],
            "verified": overlap_ratio(context, chunk_text) >= VERIFY_THRESHOLD,
        })
    return citations
