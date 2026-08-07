"""文件解析器测试 - TXT/DOCX 解析 + 不支持格式拒绝"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.utils.file_parser import parse_file


def test_parse_txt(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("第一段\n\n第二段\n\n第三段", encoding="utf-8")
    result = parse_file(str(f))
    assert result["success"] is True
    assert result["page_count"] == 3
    texts = [p["text"] for p in result["pages"]]
    assert "第一段" in texts and "第三段" in texts
    assert [p["page_no"] for p in result["pages"]] == [1, 2, 3]


def test_parse_docx(tmp_path):
    from docx import Document as DocxDocument

    doc = DocxDocument()
    doc.add_paragraph("标题段落")
    doc.add_paragraph("正文段落")
    f = tmp_path / "doc.docx"
    doc.save(str(f))
    result = parse_file(str(f))
    assert result["success"] is True
    texts = [p["text"] for p in result["pages"]]
    assert "标题段落" in texts and "正文段落" in texts


def test_unsupported_extension(tmp_path):
    f = tmp_path / "doc.exe"
    f.write_bytes(b"MZ")
    result = parse_file(str(f))
    assert result["success"] is False
