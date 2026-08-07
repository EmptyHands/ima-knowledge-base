"""文件解析 - PDF按页 / DOCX按段落 / TXT按段落, 统一返回 pages 结构"""
import logging
import os
import hashlib

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}


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
    pages = []
    for p in doc.paragraphs:
        if p.text.strip():
            pages.append({"page_no": len(pages) + 1, "text": p.text})
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
    pages = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            pages.append({"page_no": len(pages) + 1, "text": stripped})
    return {"success": True, "pages": pages, "page_count": len(pages), "metadata": {}}
