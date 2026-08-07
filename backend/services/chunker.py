"""分块 - 不跨页, 块大小/重叠从配置读取"""
from typing import List

from backend.core.config import get_config


def chunk_pages(pages: list[dict]) -> list[dict]:
    """pages: [{page_no, text}] → [{text, page, chunk_index}]
    单页超长时可拆为多块, 但块不越过页边界"""
    config = get_config()
    size = config.chunk_size
    overlap = config.chunk_overlap
    chunks: list[dict] = []
    for page in pages:
        text = page["text"]
        page_no = page["page_no"]
        if len(text) <= size:
            chunks.append({"text": text, "page": page_no, "chunk_index": len(chunks)})
            continue
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            chunks.append({"text": text[start:end], "page": page_no, "chunk_index": len(chunks)})
            if end == len(text):
                break
            start = max(start + size - overlap, start + 1)
    return chunks
