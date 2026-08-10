"""Qdrant vector store - 支持 local / ollama / openai embedding 后端 + BM25 稀疏兜底"""
import logging
import hashlib
import asyncio
import re
from collections import Counter
from typing import Optional
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue,
    SparseVectorParams, SparseVector,
)
from .config import get_config, EmbeddingProvider

STOP_WORDS = {"的", "了", "在", "是", "和", "与", "及", "或", "就", "都", "而", "也", "之", "等", "吗", "呢"}


def tokenize(text: str) -> list[str]:
    """中文 jieba 分词 + 英文按空白分词, 过滤停用词与纯符号噪音"""
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

logger = logging.getLogger(__name__)

# common embedding dimensions
EMBEDDING_DIMS = {
    "all-MiniLM-L6-v2": 384,
    "all-mpnet-base-v2": 768,
    "bge-small-zh-v1.5": 512,
    "bge-large-zh-v1.5": 1024,
    "bge-m3": 1024,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "nomic-embed-text": 768,
}


class VectorStore:
    def __init__(self):
        config = get_config()
        api_key = config.qdrant.api_key
        self.client = QdrantClient(host=config.qdrant.host, port=config.qdrant.port,
                                   **({"api_key": api_key} if api_key else {}), https=False)
        self.collection_name = config.qdrant.collection_name
        self.embedding_provider = config.embedding.provider
        self.embedding_model_name = config.embedding.model_name
        self._local_model = None
        self._openai_client = None
        self._ollama_url = None
        self._init_embedding_backend(config)
        self._ensure_collection()

    def _init_embedding_backend(self, config):
        if self.embedding_provider == EmbeddingProvider.LOCAL:
            from sentence_transformers import SentenceTransformer
            device = config.embedding.local_device
            logger.info(f"Loading local embedding model: {self.embedding_model_name} on {device}")
            self._local_model = SentenceTransformer(self.embedding_model_name, device=device)
            self._embed_dim = self._local_model.get_sentence_embedding_dimension()
            logger.info(f"Local model loaded, dim={self._embed_dim}")
        elif self.embedding_provider == EmbeddingProvider.OLLAMA:
            import aiohttp
            self._ollama_url = (config.embedding.base_url or "http://localhost:11434").rstrip("/")
            self._ollama_session = None
            self._embed_dim = EMBEDDING_DIMS.get(self.embedding_model_name, 768)
            logger.info(f"Using Ollama embedding: {self.embedding_model_name}")
        else:
            from openai import AsyncOpenAI
            self._openai_client = AsyncOpenAI(
                api_key=config.embedding.api_key or config.llm.api_key,
                base_url=config.embedding.base_url or config.llm.base_url or "https://api.openai.com/v1",
            )
            self._embed_dim = EMBEDDING_DIMS.get(self.embedding_model_name, 1536)
            logger.info(f"Using OpenAI embedding: {self.embedding_model_name}")

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

    async def _embed(self, text: str) -> list[float]:
        if self.embedding_provider == EmbeddingProvider.LOCAL:
            return await asyncio.to_thread(self._local_model.encode, text, normalize_embeddings=True)
        elif self.embedding_provider == EmbeddingProvider.OLLAMA:
            import aiohttp
            if not getattr(self, '_ollama_session', None):
                self._ollama_session = aiohttp.ClientSession()
            async with self._ollama_session.post(
                f"{self._ollama_url}/api/embeddings",
                json={"model": self.embedding_model_name, "prompt": text}
            ) as resp:
                data = await resp.json()
                if "error" in data:
                    raise Exception(f"Ollama embedding error: {data['error']}")
                emb = data.get("embedding") or data.get("embeddings")
                if emb is None:
                    raise Exception(f"Unexpected Ollama response: {list(data.keys())}")
                return emb
        else:
            resp = await self._openai_client.embeddings.create(model=self.embedding_model_name, input=text)
            return resp.data[0].embedding

    async def add_documents(self, kb_id: str, doc_id: str, user_id: str,
                            chunks: list[dict], metadata: dict = None) -> int:
        """chunks: [{"text": str, "page": int, "chunk_index": int}, ...]
        返回实际写入的向量数"""
        if not chunks:
            return 0
        points = []
        for c in chunks:
            text = c.get("text", "").strip()
            if not text:
                continue
            embedding = await self._embed(text)
            sparse_vec = build_sparse_vector(tokenize(text))
            payload = {
                "kb_id": kb_id,
                "doc_id": doc_id,
                "user_id": user_id,
                "page": c.get("page", 0),
                "chunk_index": c.get("chunk_index", 0),
                "text": text,
                **(metadata or {}),
            }
            point_id = self._point_id(f"{doc_id}_{c.get('chunk_index', 0)}_{text[:50]}")
            points.append(PointStruct(id=point_id, vector={"dense": embedding, "sparse": sparse_vec},
                                      payload=payload))
        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)
            logger.info(f"Added {len(points)} vectors (kb={kb_id}, doc={doc_id})")
        return len(points)

    async def search(self, kb_id: str, query: str, top_k: int = 5) -> list[dict]:
        query_embedding = await self._embed(query)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            using="dense",
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

    async def sparse_search(self, kb_id: str, query: str, top_k: int = 5) -> list[dict]:
        """关键词(BM25)检索, 返回结构与 search 一致"""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        sparse_vec = build_sparse_vector(query_tokens)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=SparseVector(indices=sparse_vec["indices"], values=sparse_vec["values"]),
            using="sparse",
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

    async def delete_document(self, doc_id: str):
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
        )
        logger.info(f"Deleted vectors for doc={doc_id}")

    async def delete_knowledge_base(self, kb_id: str):
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        )
        logger.info(f"Deleted vectors for kb={kb_id}")

    def _point_id(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def close(self):
        self.client.close()
        if self.embedding_provider == EmbeddingProvider.OLLAMA and getattr(self, '_ollama_session', None):
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self._ollama_session.close())
            except Exception:
                pass


_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
