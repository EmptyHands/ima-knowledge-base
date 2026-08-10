# DEV-004 检索无结果兜底机制 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 空库/检索无结果时给出固定反问答复,新增 BM25 关键词检索降级兜底,支持用户确认后强制联网搜索。

**Architecture:** Qdrant 双向量集合(dense 语义 + sparse 关键词,同一 point),检索三级降级(dense → 阈值判断 → sparse → 空),chat 层空库判断 + 反问模板 + 确认词识别后强制联网。反问轮不调用大模型。

**Tech Stack:** FastAPI / Qdrant(qdrant-client 1.19,原生 sparse)+ jieba / pytest(伪向量 + 伪 LLM 离线测试)

**前置说明:** 设计文档 `docs/plans/2026-08-10-dev004-no-result-fallback-design.md` 已确认。其中空库反问模板补一个缺口:模板内包含原问题(句式与无结果版统一),以便用户确认「需要」后能提取原问题联网——原设计模板无原问题,用户只回「需要」无法构成检索问题。

---

## Task 0: 安装 jieba 依赖

**Files:**
- Modify: `requirements.txt`

**Step 1:** `requirements.txt` 的「HTTP / 工具」段追加一行 `jieba>=0.42.1`

**Step 2:** 安装

```bash
cd E:/py_code/Agent/AgentTry/ima-knowledge-base && venv/Scripts/python.exe -m pip install jieba
```

Expected: `Successfully installed jieba-0.42.1`

**Step 3:** 验证导入

```bash
venv/Scripts/python.exe -c "import jieba; print(list(jieba.cut('深度学习需要大量数据'))[:3])"
```

Expected: 输出分词列表(如 `['深度', '学习', '需要', ...]`),无报错

**Step 4:** Commit

```bash
git add requirements.txt && git commit -m "chore: add jieba dependency for BM25 sparse retrieval"
```

---

## Task 1: config 新增 dense 分数阈值配置

**Files:**
- Modify: `backend/core/config.py:73-75`(AppConfig 字段区)、`:103`(__post_init__ 区)
- Modify: `.env.example`(检索参数段)

**Step 1: 写失败测试** — 新增 `tests/test_config.py`:

```python
"""配置测试 - 新增检索阈值项"""
import backend.core.config as config_module


def test_retrieval_dense_threshold_default(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_DENSE_THRESHOLD", raising=False)
    config_module._config = None
    cfg = config_module.get_config()
    assert cfg.retrieval_dense_threshold == 0.35


def test_retrieval_dense_threshold_from_env(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_DENSE_THRESHOLD", "0.5")
    config_module._config = None
    cfg = config_module.get_config()
    assert cfg.retrieval_dense_threshold == 0.5
```

**Step 2: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/test_config.py -v
```

Expected: FAIL — `AttributeError: 'AppConfig' object has no attribute 'retrieval_dense_threshold'`

**Step 3: 实现**

`backend/core/config.py` AppConfig 字段区(`retrieval_top_k: int = 5` 后)加:

```python
    retrieval_dense_threshold: float = 0.35
```

`__post_init__` 末尾(`chunk_overlap` 行后)加:

```python
        self.retrieval_dense_threshold = float(os.getenv("RETRIEVAL_DENSE_THRESHOLD", "0.35"))
```

`.env.example` 检索参数段(`RETRIEVAL_TOP_K` 后)加:

```
# 语义检索最高分低于该值时视为未命中, 触发关键词(BM25)检索兜底
RETRIEVAL_DENSE_THRESHOLD=0.35
```

**Step 4: 跑测试确认通过**

```bash
venv/Scripts/python.exe -m pytest tests/test_config.py -v
```

Expected: PASS 2 passed

**Step 5: Commit**

```bash
git add tests/test_config.py backend/core/config.py .env.example && git commit -m "feat: add retrieval dense score threshold config"
```

---

## Task 2: vector_store 双向量 + 分词 + sparse 检索

**Files:**
- Modify: `backend/core/vector_store.py`
- Modify: `tests/test_vector_store.py`(store fixture 改双向量创建)
- Create: `tests/test_sparse.py`

**Step 1: 写失败测试** — `tests/test_sparse.py`:

```python
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
```

**Step 2: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/test_sparse.py -v
```

Expected: FAIL — `ImportError: cannot import name 'tokenize'`

**Step 3: 实现 tokenize / build_sparse_vector** — `backend/core/vector_store.py` 顶部 import 区加:

```python
import re
from collections import Counter

STOP_WORDS = {"的", "了", "在", "是", "和", "与", "及", "或", "就", "都", "而", "也", "之", "等", "吗", "呢"}


def tokenize(text: str) -> list[str]:
    """中文 jieba 分词 + 英文按空白分词, 过滤停用词与单字符噪音"""
    import jieba
    words = jieba.lcut(text.lower())
    return [w.strip() for w in words
            if w.strip() and w.strip() not in STOP_WORDS and not re.fullmatch(r"[\W_]+", w)]


def _term_index(token: str) -> int:
    """稳定哈希: 同一 token 永远映射到同一 index, 避免词表漂移"""
    return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % (1 << 24)


def build_sparse_vector(tokens: list[str]) -> dict:
    """TF 词频稀疏向量: {"indices": [...], "values": [...]}"""
    if not tokens:
        return {"indices": [], "values": []}
    counts = Counter(tokens)
    pairs = sorted(((_term_index(t), float(c)) for t, c in counts.items()),
                   key=lambda x: x[0])
    return {"indices": [i for i, _ in pairs], "values": [v for _, v in pairs]}
```

**Step 4: 实现双向量 collection** — `backend/core/vector_store.py`:

import 区改为:

```python
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue,
    SparseVectorParams, SparseVector,
)
```

`_ensure_collection` 改为:

```python
    def _ensure_collection(self):
        dim = getattr(self, '_embed_dim', 768)
        try:
            existing = self.client.get_collection(self.collection_name)
            params = existing.config.params
            vectors = params.vectors
            existing_dim = vectors["dense"].size if isinstance(vectors, dict) else vectors.size
            has_sparse = bool(params.sparse_vectors)
            if not has_sparse:
                raise ValueError(
                    f"现有 collection 缺少关键词(sparse)索引, 无法启用兜底检索。\n"
                    f"请执行以下步骤完成迁移:\n"
                    f"  1. 手动删除旧 collection: client.delete_collection('{self.collection_name}')\n"
                    f"  2. 重启应用, 将自动创建双向量 collection\n"
                    f"  3. 重新导入所有文档以重建向量索引"
                )
            if existing_dim != dim:
                raise ValueError(
                    f"嵌入向量维度不匹配: 已有 collection 为 {existing_dim}d, "
                    f"当前模型 {self.embedding_model_name} 为 {dim}d。\n"
                    f"请执行以下步骤完成迁移:\n"
                    f"  1. 手动删除旧 collection: client.delete_collection('{self.collection_name}')\n"
                    f"  2. 重启应用, 将自动创建新 collection\n"
                    f"  3. 重新导入所有文档以重建向量索引"
                )
        except ValueError:
            raise
        except Exception:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": VectorParams(size=dim, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(),
                },
            )
            logger.info(f"Created dual-vector collection {self.collection_name} (dim={dim})")
```

**Step 5: 改造 add_documents 写入双向量** — `backend/core/vector_store.py` 中 `add_documents` 循环内,`embedding = await self._embed(text)` 后加:

```python
            sparse_vec = build_sparse_vector(tokenize(text))
```

`points.append(PointStruct(...))` 的 `vector=embedding` 改为:

```python
            points.append(PointStruct(
                id=point_id,
                vector={"dense": embedding, "sparse": sparse_vec},
                payload={...同现有...},
            ))
```

**Step 6: 新增 sparse_search 方法** — 在 `search` 方法后加:

```python
    async def sparse_search(self, kb_id: str, query: str, top_k: int = 5) -> list[dict]:
        """关键词(BM25)检索, 返回结构与 search 一致"""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        sparse_vec = build_sparse_vector(query_tokens)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=SparseVector(indices=sparse_vec["indices"], values=sparse_vec["values"]),
            query_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
            limit=top_k, with_payload=True,
        )
        return [
            {
                "score": r.score,
                "text": r.payload.get("text", ""),
                "doc_id": r.payload.get("doc_id", ""),
                "page": r.payload.get("page", 0),
                "chunk_index": r.payload.get("chunk_index", 0),
            }
            for r in response.points
        ]
```

**Step 7: 改造测试 fixture** — `tests/test_vector_store.py` 中 `store` fixture 的 `create_collection` 改为双向量:

```python
    vs.client.create_collection(
        collection_name=TEST_COLLECTION,
        vectors_config={"dense": VectorParams(size=vs._embed_dim, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams()},
    )
```

import 行加 `SparseVectorParams`。

**Step 8: 跑测试**

```bash
venv/Scripts/python.exe -m pytest tests/test_sparse.py tests/test_vector_store.py -v
```

Expected: PASS(全部)— 新增 6 个 sparse 测试 + 原 3 个 vector_store 测试

**Step 9: Commit**

```bash
git add backend/core/vector_store.py tests/test_sparse.py tests/test_vector_store.py && git commit -m "feat: dual-vector collection with BM25 sparse fallback search"
```

---

## Task 3: retrieval 三级降级管线

**Files:**
- Modify: `backend/core/retrieval.py:20-35`(`vector_search`)
- Modify: `tests/test_retrieval.py`(新增降级测试)

**Step 1: 写失败测试** — `tests/test_retrieval.py` 追加:

```python
class FakeHybridStore:
    """可控 dense/sparse 结果, 模拟降级触发"""

    def __init__(self, dense=None, sparse=None):
        self._dense = dense
        self._sparse = sparse

    async def search(self, kb_id, query, top_k=5):
        return (self._dense or [])[:top_k]

    async def sparse_search(self, kb_id, query, top_k=5):
        return (self._sparse or [])[:top_k]


DENSE_HIT = [{"score": 0.81, "text": "Transformer 使用自注意力", "doc_id": "doc1", "page": 3, "chunk_index": 0}]
DENSE_LOW = [{"score": 0.12, "text": "低分片段", "doc_id": "doc1", "page": 1, "chunk_index": 0}]
SPARSE_HIT = [{"score": 2.5, "text": "关键词命中片段 alpha beta", "doc_id": "doc2", "page": 2, "chunk_index": 0}]


@pytest.mark.asyncio
async def test_dense_high_score_no_fallback(app_client, monkeypatch):
    store = FakeHybridStore(dense=DENSE_HIT, sparse=SPARSE_HIT)
    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: store)
    result = await retrieval_module.vector_search("kb1", "Transformer 是什么")
    assert result[0]["doc_id"] == "doc1"
    assert result[0].get("search_type") == "dense"


@pytest.mark.asyncio
async def test_dense_empty_falls_back_to_sparse(app_client, monkeypatch):
    store = FakeHybridStore(dense=[], sparse=SPARSE_HIT)
    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: store)
    result = await retrieval_module.vector_search("kb1", "alpha beta")
    assert result[0]["doc_id"] == "doc2"
    assert result[0].get("search_type") == "sparse"


@pytest.mark.asyncio
async def test_dense_low_score_falls_back_to_sparse(app_client, monkeypatch):
    store = FakeHybridStore(dense=DENSE_LOW, sparse=SPARSE_HIT)
    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: store)
    result = await retrieval_module.vector_search("kb1", "alpha beta")
    assert result[0]["doc_id"] == "doc2"
    assert result[0].get("search_type") == "sparse"


@pytest.mark.asyncio
async def test_both_empty_returns_empty(app_client, monkeypatch):
    store = FakeHybridStore(dense=[], sparse=[])
    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: store)
    result = await retrieval_module.vector_search("kb1", "什么都不存在")
    assert result == []
```

**Step 2: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/test_retrieval.py -k "fallback or high_score or both_empty" -v
```

Expected: FAIL — 无 `search_type` 字段、无 sparse 兜底(或 AttributeError `sparse_search` 不存在于 FakeStore)

**Step 3: 实现** — `backend/core/retrieval.py` 中 `vector_search` 整体替换:

```python
async def vector_search(kb_id: str, question: str, top_k: int | None = None) -> list[dict]:
    """三级降级检索: dense → (空/低分) → sparse → 空

    返回 [{score, text, doc_id, page, chunk_index, doc_name, search_type}]
    """
    config = get_config()
    top_k = top_k or config.retrieval_top_k
    store = get_vector_store()

    dense = await store.search(kb_id, question, top_k=top_k)
    if dense and dense[0]["score"] >= config.retrieval_dense_threshold:
        return _attach_doc_names(dense, "dense")

    sparse = await store.sparse_search(kb_id, question, top_k=top_k)
    if sparse:
        return _attach_doc_names(sparse, "sparse")
    return []


def _attach_doc_names(chunks: list[dict], search_type: str) -> list[dict]:
    """补充 doc_name 文档名与 search_type 标记"""
    doc_ids = {c["doc_id"] for c in chunks}
    db = get_db_session()
    try:
        rows = db.query(Document.id, Document.filename).filter(Document.id.in_(doc_ids)).all()
        name_map = {row.id: row.filename for row in rows}
    finally:
        db.close()
    return [{**c, "doc_name": name_map.get(c["doc_id"], ""), "search_type": search_type} for c in chunks]
```

`retrieval.py` 顶部 import 加 `from backend.core.config import get_config`。

**Step 4: 跑全部检索测试**

```bash
venv/Scripts/python.exe -m pytest tests/test_retrieval.py -v
```

Expected: PASS(原 4 个 + 新 4 个)

**Step 5: Commit**

```bash
git add backend/core/retrieval.py tests/test_retrieval.py && git commit -m "feat: three-tier retrieval fallback (dense -> sparse -> empty)"
```

---

## Task 4: retriever_agent 支持强制联网

**Files:**
- Modify: `backend/agents/retriever_agent.py`
- Modify: `tests/test_retrieval.py`(新增 agent 层测试)

**Step 1: 写失败测试** — `tests/test_retrieval.py` 追加:

```python
@pytest.mark.asyncio
async def test_retrieve_force_web_triggers_web_search(app_client, monkeypatch, sample_chunks):
    calls = []

    async def fake_web_search(query, max_results=5):
        calls.append(query)
        return [{"title": "标题", "url": "https://example.com", "snippet": "摘要"}]

    monkeypatch.setattr(retrieval_module, "get_vector_store", lambda: FakeStore(sample_chunks))
    monkeypatch.setattr(retriever_module, "web_search", fake_web_search)

    # 无网络意图, 但 force_web=True 仍应触发联网
    await retriever_module.retrieve("知识库如何分块", "kb1", force_web=True)
    assert calls == ["知识库如何分块"]

    calls.clear()
    await retriever_module.retrieve("知识库如何分块", "kb1", force_web=False)
    assert calls == []
```

**Step 2: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/test_retrieval.py::test_retrieve_force_web_triggers_web_search -v
```

Expected: FAIL — `TypeError: retrieve() got an unexpected keyword argument 'force_web'`

**Step 3: 实现** — `backend/agents/retriever_agent.py` 整体替换:

```python
"""RetrieverAgent - 检索智能体: 三级降级检索 + 意图识别网络搜索"""
from backend.core.retrieval import detect_web_intent, vector_search, web_search


async def retrieve(question: str, kb_id: str, top_k: int = 5, force_web: bool = False) -> dict:
    """检索入口, 返回 {"chunks": [...], "web_results": [...]}

    force_web=True 时无条件触发网络搜索(反问确认后的重检索)
    """
    chunks = await vector_search(kb_id, question, top_k=top_k)
    web_results = []
    if force_web or detect_web_intent(question):
        web_results = await web_search(question)
    return {"chunks": chunks, "web_results": web_results}
```

**Step 4: 跑测试**

```bash
venv/Scripts/python.exe -m pytest tests/test_retrieval.py -v
```

Expected: PASS(全部 9 个)

**Step 5: Commit**

```bash
git add backend/agents/retriever_agent.py tests/test_retrieval.py && git commit -m "feat: retriever supports force web search for fallback confirmation"
```

---

## Task 5: chat 反问闭环(空库判断 + 模板 + 确认词)

**Files:**
- Modify: `backend/api/routes/chat.py`
- Modify: `tests/conftest.py`(fake_retrieve 签名加 force_web)
- Create: `tests/test_fallback.py`

**Step 1: 写失败测试** — `tests/test_fallback.py`:

```python
"""检索无结果兜底机制测试 - 空库反问 / 无结果反问 / 确认联网闭环"""
import json

import pytest


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event is not None:
            events.append((event, data))
    return events


@pytest.fixture()
def kb_id(app_client, auth_headers):
    resp = app_client.post("/api/v1/knowledge-bases",
                           json={"name": "兜底测试库", "description": ""},
                           headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.fixture()
def conv_id(app_client, auth_headers, kb_id):
    resp = app_client.post(f"/api/v1/conversations?kb_id={kb_id}",
                           json={"kb_id": kb_id, "title": "新对话"},
                           headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _ask(app_client, conv_id, question, headers):
    return app_client.post(f"/api/v1/conversations/{conv_id}/messages",
                           json={"question": question}, headers=headers)


def test_empty_kb_asks_web_fallback(app_client, auth_headers, kb_id, conv_id):
    """空库: 固定反问, 事件序列 status -> done, 无 chunk"""
    resp = _ask(app_client, conv_id, "什么是机器学习", auth_headers)
    events = _parse_sse(resp.text)
    types = [e for e, _ in events]
    assert types == ["status", "citations", "done"]
    msg = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                         headers=auth_headers).json()
    assert msg[1]["role"] == "assistant"
    assert "还没有任何文档" in msg[1]["content"]
    assert "是否需要联网搜索" in msg[1]["content"]


def test_no_result_asks_web_fallback(app_client, auth_headers, kb_id, conv_id, monkeypatch):
    """有文档但检索全空: 反问带原问题"""
    from backend.models.database import Document
    from backend.core.database import get_db_session
    db = get_db_session()
    db.add(Document(id="doc-x", kb_id=kb_id, filename="x.pdf", file_path="/tmp/x.pdf"))
    db.commit()
    db.close()

    import backend.agents.retriever_agent as retriever_module

    async def _empty(question, kb_id, top_k=5, force_web=False):
        return {"chunks": [], "web_results": []}

    monkeypatch.setattr(retriever_module, "retrieve", _empty)

    resp = _ask(app_client, conv_id, "怎么种苹果", auth_headers)
    events = _parse_sse(resp.text)
    assert [e for e, _ in events] == ["status", "citations", "done"]
    msg = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                         headers=auth_headers).json()
    assert "未找到与『怎么种苹果』相关的内容" in msg[1]["content"]


def test_confirm_word_triggers_force_web(app_client, auth_headers, kb_id, conv_id, monkeypatch):
    """反问后回复确认词: 提取原问题并强制联网"""
    from backend.models.database import Document
    from backend.core.database import get_db_session
    db = get_db_session()
    db.add(Document(id="doc-x", kb_id=kb_id, filename="x.pdf", file_path="/tmp/x.pdf"))
    db.commit()
    db.close()

    import backend.agents.retriever_agent as retriever_module

    calls = []

    async def _fake_retrieve(question, kb_id, top_k=5, force_web=False):
        calls.append((question, force_web))
        return {"chunks": [], "web_results": [{"title": "网络结果", "url": "http://x", "snippet": "s"}]}

    monkeypatch.setattr(retriever_module, "retrieve", _fake_retrieve)

    # 第一轮: 无结果反问
    _ask(app_client, conv_id, "怎么种苹果", auth_headers)

    # 第二轮: 回复确认词
    resp = _ask(app_client, conv_id, "需要", auth_headers)
    events = _parse_sse(resp.text)
    assert "chunk" in [e for e, _ in events]
    assert calls[-1] == ("怎么种苹果", True), "应提取原问题并强制联网"


def test_non_confirm_reply_not_force_web(app_client, auth_headers, kb_id, conv_id, monkeypatch):
    """非确认词回复: 不触发强制联网"""
    import backend.agents.retriever_agent as retriever_module

    calls = []

    async def _fake_retrieve(question, kb_id, top_k=5, force_web=False):
        calls.append((question, force_web))
        return {"chunks": [], "web_results": []}

    monkeypatch.setattr(retriever_module, "retrieve", _fake_retrieve)

    _ask(app_client, conv_id, "怎么种苹果", auth_headers)
    _ask(app_client, conv_id, "明天再说", auth_headers)
    assert calls[-1] == ("明天再说", False)


def test_confirmed_but_web_unavailable(app_client, auth_headers, kb_id, conv_id, monkeypatch):
    """确认联网但未配置网络搜索: 固定提示不可用"""
    import backend.agents.retriever_agent as retriever_module

    async def _empty(question, kb_id, top_k=5, force_web=False):
        return {"chunks": [], "web_results": []}

    monkeypatch.setattr(retriever_module, "retrieve", _empty)
    _ask(app_client, conv_id, "怎么种苹果", auth_headers)
    resp = _ask(app_client, conv_id, "需要", auth_headers)
    msg = app_client.get(f"/api/v1/conversations/{conv_id}/messages",
                         headers=auth_headers).json()
    assert "联网搜索" in msg[-1]["content"]
```

**Step 2: 更新 conftest 的 fake_retrieve 签名**

`tests/conftest.py` 中 `_fake` 改为接受 `force_web`:

```python
    async def _fake(question, kb_id, top_k=5, force_web=False):
```

**Step 3: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/test_fallback.py -v
```

Expected: FAIL — 空库仍走 LLM(无「还没有任何文档」)、无确认词识别

**Step 4: 实现** — `backend/api/routes/chat.py`:

import 区加 `import re`(`Document` 已在 import 中)。模块常量加:

```python
EMPTY_KB_FALLBACK = "当前知识库还没有任何文档。知识库中未找到与『{question}』相关的内容。是否需要联网搜索?回复『需要』即可。"
NO_RESULT_FALLBACK = "知识库中未找到与『{question}』相关的内容。是否需要联网搜索?回复『需要』即可。"
WEB_UNAVAILABLE = "联网搜索当前不可用(未配置 TAVILY_API_KEY), 请换个问法或上传相关文档后重试。"
CONFIRM_WORDS = ("需要", "要", "好", "是", "可以", "联网", "搜索", "用")
_RE_FALLBACK_QUESTION = re.compile(r"未找到与『(.+?)』相关的内容")


def _confirm_question(history: list[dict], question: str) -> tuple[str, bool]:
    """反问确认识别: 最近助手消息是反问模板且本次回复为确认词时, 返回(原问题, True)"""
    q = question.strip().strip("。.!！?？ ")
    last_assistant = next((m for m in reversed(history) if m["role"] == "assistant"), None)
    if last_assistant:
        m = _RE_FALLBACK_QUESTION.search(last_assistant["content"] or "")
        if m and q in CONFIRM_WORDS:
            return m.group(1), True
    return question, False
```

`ask()` 函数体替换(保留历史读取与用户消息入库,新增空库计数与确认识别):

```python
    conv = _get_owned_conv(db, conv_id, user)
    kb = _check_kb_owned(db, conv.kb_id, user)
    question = req.question.strip()

    history_rows = db.query(Message).filter(Message.conversation_id == conv_id) \
        .order_by(Message.created_at.desc()).limit(HISTORY_LIMIT).all()
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    doc_count = db.query(Document).filter(Document.kb_id == conv.kb_id).count()
    question, force_web = _confirm_question(history, question)

    user_msg = Message(conversation_id=conv_id, role="user", content=req.question.strip())
    db.add(user_msg)
    db.commit()
```

`async def gen()` 替换:

```python
    async def gen():
        try:
            if doc_count == 0 and not force_web:
                text = EMPTY_KB_FALLBACK.format(question=question)
                yield _sse("status", {"text": "知识库为空, 未进行检索"})
                yield from _finish_fallback(text)
                return

            yield _sse("status", {"text": "正在检索知识库..."})
            retrieval = await retriever_agent.retrieve(question, conv.kb_id, force_web=force_web)
            chunks, web_results = retrieval["chunks"], retrieval["web_results"]
            if not chunks and not web_results:
                if force_web:
                    text = WEB_UNAVAILABLE
                else:
                    text = NO_RESULT_FALLBACK.format(question=question)
                yield _sse("status", {"text": "知识库中未检索到相关内容"})
                yield from _finish_fallback(text)
                return

            answer_parts = []
            citations = []
            async for event in answer_agent.stream(question, history, chunks, web_results):
                if event["type"] == "chunk":
                    answer_parts.append(event["data"])
                    yield _sse("chunk", {"text": event["data"]})
                elif event["type"] == "citations":
                    citations = event["data"]
                else:
                    yield _sse("status", {"text": event["data"]})

            assistant_msg = Message(conversation_id=conv_id, role="assistant",
                                    content="".join(answer_parts),
                                    citations_json=citations or None)
            db.add(assistant_msg)
            if conv.title == "新对话":
                conv.title = question[:20]
            db.commit()

            yield _sse("citations", {"items": citations})
            yield _sse("done", {"message_id": assistant_msg.id})
        except Exception as e:
            logger.exception("问答管线失败")
            yield _sse("error", {"text": f"生成失败: {str(e)[:200]}"})
```

新增辅助函数(gen 定义之前,嵌套在 `ask` 内):

```python
    def _finish_fallback(text: str):
        """反问/不可用回复: 固定文本入库 + citations + done, 不调用大模型"""
        assistant_msg = Message(conversation_id=conv_id, role="assistant",
                                content=text, citations_json=None)
        db.add(assistant_msg)
        if conv.title == "新对话":
            conv.title = text[:20]
        db.commit()
        yield _sse("citations", {"items": []})
        yield _sse("done", {"message_id": assistant_msg.id})
```

**Step 5: 跑新测试**

```bash
venv/Scripts/python.exe -m pytest tests/test_fallback.py -v
```

Expected: PASS(5 个)

**Step 6: 回归全部测试**

```bash
venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: PASS 全绿(51 + 新增)。若 `test_chat_stream.py` 或 `test_e2e_flow.py` 失败,检查原因:它们用 `fake_retrieve`(已更新签名)且知识库非空(有上传文档流程),不应受影响。

**Step 7: Commit**

```bash
git add backend/api/routes/chat.py tests/conftest.py tests/test_fallback.py && git commit -m "feat: fallback ask-web confirmation flow for empty/no-result retrieval"
```

---

## Task 6: README 与版本记录

**Files:**
- Modify: `README.md`

**Step 1:** README「功能」段「混合检索」条目后追加:

```markdown
- **检索兜底**: 语义检索无结果或分数过低时,自动降级 BM25 关键词检索;两轮皆空则固定反问「是否需要联网搜索」,用户回复确认词后提取原问题强制联网作答
```

**Step 2:** README「已知限制」段追加一行:

```markdown
- 存量向量数据需重建:旧 collection 缺少关键词索引,启动时会提示删除重建后再导入文档
```

**Step 3:** README「版本变更记录」表格追加:

```markdown
| v1.0.2 | 2026-08-10 | 修复 DEV-004:检索无结果兜底(双向量 BM25 降级 + 空库/无结果反问 + 确认后强制联网) |
```

**Step 4: 跑回归确认无破坏**

```bash
venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: PASS 全绿

**Step 5: Commit**

```bash
git add README.md && git commit -m "docs: DEV-004 fallback mechanism in README"
```

---

## 完成标准(验收清单)

1. `pytest tests/` 全绿(51 原有 + 新增 17 个左右)
2. 空库提问:回答为固定反问(含「还没有任何文档」「是否需要联网搜索」),事件序列 status → citations → done,无 chunk,未调大模型
3. 有文档检索全空:反问含原问题「未找到与『X』相关的内容」
4. 回复「需要」:重检索使用原问题且 force_web=True
5. 回复非确认词:正常处理,不强制联网
6. 确认联网但未配置网络:固定回复不可用提示
7. 正常有结果:回答链路与事件序列与改前一致
8. README 与 .env.example 已同步
