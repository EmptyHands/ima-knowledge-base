"""分块器测试 - 不跨页 + 超长页拆分 + chunk_index 连续"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import backend.services.chunker as chunker_module
from backend.services.chunker import chunk_pages


@pytest.fixture()
def small_chunks(monkeypatch):
    class FakeConfig:
        chunk_size = 20
        chunk_overlap = 4

    monkeypatch.setattr(chunker_module, "get_config", lambda: FakeConfig())


def test_short_page_single_chunk(small_chunks):
    pages = [{"page_no": 1, "text": "hello world"}]
    chunks = chunk_pages(pages)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "hello world"
    assert chunks[0]["page"] == 1
    assert chunks[0]["chunk_index"] == 0


def test_long_page_split_without_crossing(small_chunks):
    pages = [{"page_no": 2, "text": "a" * 50}]
    chunks = chunk_pages(pages)
    assert len(chunks) >= 3
    assert all(c["page"] == 2 for c in chunks)
    assert all(len(c["text"]) <= 20 for c in chunks)
    # 相邻块有重叠
    assert chunks[1]["text"].startswith(chunks[0]["text"][-4:])


def test_chunk_index_continuous_across_pages(small_chunks):
    pages = [
        {"page_no": 1, "text": "b" * 30},
        {"page_no": 2, "text": "c" * 10},
    ]
    chunks = chunk_pages(pages)
    indexes = [c["chunk_index"] for c in chunks]
    assert indexes == list(range(len(chunks)))
    # 第二页块不包含第一页文本
    assert all("b" not in c["text"] for c in chunks if c["page"] == 2)
