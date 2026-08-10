"""BM25 稀疏向量与关键词检索测试 - 不依赖真实 embedding"""
import pytest

from backend.core.vector_store import tokenize, build_sparse_vector


def test_tokenize_stable():
    assert tokenize("深度学习需要大量数据") == tokenize("深度学习需要大量数据")
    assert "深度" in tokenize("深度学习需要大量数据")


def test_tokenize_mixed_en():
    tokens = tokenize("Transformer uses attention 机制")
    assert "transformer" in tokens
    assert "attention" in tokens


def test_tokenize_empty_and_punct():
    assert tokenize("") == []
    assert tokenize(",,，。!") == []


def test_build_sparse_vector_tf():
    vec = build_sparse_vector(["深度", "学习", "深度", "深度"])
    by_token = {t: build_sparse_vector(["深度"])["indices"][0] for t in ["深度"]}
    token_index = by_token["深度"]
    values = dict(zip(vec["indices"], vec["values"]))
    assert values[token_index] == 3.0


def test_build_sparse_vector_deterministic():
    a = build_sparse_vector(["深度", "学习"])
    b = build_sparse_vector(["深度", "学习"])
    assert a == b


def test_build_sparse_vector_empty():
    assert build_sparse_vector([]) == {"indices": [], "values": []}
