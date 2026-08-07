"""CitationAgent - 引用解析与校验 (overlap 阈值校验在 Task 19 完整实现)"""
import re

CITATION_PATTERN = re.compile(r"\[(\d+)\]")
SNIPPET_CHARS = 200


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


def build_citations(answer_text: str, chunks: list[dict]) -> list[dict]:
    """按回答中的 [n] 映射检索片段, 返回 [{n, doc_name, page, snippet, verified}]"""
    citations = []
    for n in parse_citation_numbers(answer_text):
        chunk = chunks[n - 1] if 0 <= n - 1 < len(chunks) else None
        if chunk is None:
            continue
        citations.append({
            "n": n,
            "doc_name": chunk.get("doc_name", ""),
            "page": chunk.get("page", 0),
            "snippet": (chunk.get("text") or "")[:SNIPPET_CHARS],
            "verified": True,  # 引用上下文与片段重叠率阈值 0.6 校验在 Task 19 接入
        })
    return citations
