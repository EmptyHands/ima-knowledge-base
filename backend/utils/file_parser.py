"""文件解析 - PDF按页 / DOCX按段落 / TXT按行, 短段打包后统一返回 pages 结构"""
import logging
import os
import hashlib

from backend.core.config import get_config

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}

# 短页合并阈值: 低于此长度的页(标题/短句)并入下一页, 避免无内容的碎片 chunk
MIN_PAGE_CHARS = 80


def _pack_segments(segments: list[str]) -> list[dict]:
    """把文本段打包成有内容的页: 累积到 chunk_size 附近, 过短页并入下一页

    TXT 的行与 DOCX 的段落常是标题或短句, 直接各自成页会让索引碎片化
    (chunk 只有十几字, LLM 无内容可引用); 打包后再交给 chunker 切分。
    """
    target = get_config().chunk_size
    merged: list[str] = []
    buf = ""
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        if not buf:
            buf = seg
        elif len(buf) + len(seg) <= target:
            buf += "\n" + seg
        else:
            merged.append(buf)
            buf = seg
    if buf:
        merged.append(buf)
    if len(merged) <= 1:
        return [{"page_no": i + 1, "text": t} for i, t in enumerate(merged)]
    final: list[str] = []
    skip = False
    for i, m in enumerate(merged):
        if skip:
            skip = False
            continue
        if i + 1 < len(merged) and len(m) < MIN_PAGE_CHARS:
            final.append(m + "\n" + merged[i + 1])
            skip = True
        else:
            final.append(m)
    return [{"page_no": i + 1, "text": t} for i, t in enumerate(final)]


def get_file_hash(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_file(file_path: str) -> dict:
    """返回 {success, pages: [{page_no, text}], page_count, metadata}
    或 {success: False, error}。PDF 的 page_no 为页码,DOCX/TXT/MD 为段落号。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return {"success": False, "error": f"不支持的文件格式: {ext}"}

    try:
        if ext == ".pdf":
            return _parse_pdf(file_path)
        elif ext in (".docx", ".doc"):
            return _parse_docx(file_path)
        else:
            return _parse_text(file_path)
    except Exception as e:
        logger.error(f"文件解析失败 {file_path}: {e}")
        return {"success": False, "error": str(e)}


def _parse_pdf(file_path: str) -> dict:
    import pdfplumber
    pages = []
    meta = {}
    with pdfplumber.open(file_path) as pdf:
        meta = pdf.metadata or {}
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if text and text.strip():
                pages.append({"page_no": i, "text": text})
    return {
        "success": True,
        "pages": pages,
        "page_count": page_count,
        "metadata": {"title": meta.get("/Title", ""), "author": meta.get("/Author", "")},
    }


def _parse_docx(file_path: str) -> dict:
    from docx import Document
    doc = Document(file_path)
    pages = _pack_segments([p.text for p in doc.paragraphs])
    return {"success": True, "pages": pages, "page_count": len(pages), "metadata": {}}


def _parse_text(file_path: str) -> dict:
    encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
    text = None
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                text = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        return {"success": False, "error": "无法识别文件编码"}
    pages = _pack_segments(text.split("\n"))
    return {"success": True, "pages": pages, "page_count": len(pages), "metadata": {}}
