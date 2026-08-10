"""
智能知识库问答系统 核心配置模块
"""
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
import os
from pathlib import Path
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = str(_PROJECT_ROOT / "data" / "ima_kb.db")

load_dotenv()


class LLMProvider(str, Enum):
    OPENAI = "openai"
    DASHSCOPE = "dashscope"
    OLLAMA = "ollama"


class EmbeddingProvider(str, Enum):
    OPENAI = "openai"
    LOCAL = "local"
    OLLAMA = "ollama"


@dataclass
class LLMConfig:
    provider: LLMProvider = LLMProvider.OPENAI
    model_name: str = "deepseek-v4-pro"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4000
    timeout: int = 60


@dataclass
class EmbeddingConfig:
    provider: EmbeddingProvider = EmbeddingProvider.OLLAMA
    model_name: str = "nomic-embed-text"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    local_device: str = "cpu"


@dataclass
class QdrantConfig:
    host: str = "localhost"
    port: int = 6333
    api_key: Optional[str] = None
    collection_name: str = "ima_knowledge_base"


@dataclass
class AppConfig:
    app_name: str = "ima-knowledge-base"
    debug: bool = False
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000

    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)

    database_url: str = f"sqlite:///{_DEFAULT_DB}"
    jwt_secret: str = "change-me"
    jwt_expire_days: int = 7
    storage_dir: str = "./data/uploads"
    retrieval_top_k: int = 5
    retrieval_dense_threshold: float = 0.35
    chunk_size: int = 800
    chunk_overlap: int = 100

    def __post_init__(self):
        self.llm.provider = LLMProvider(os.getenv("LLM_PROVIDER", "openai"))
        self.llm.model_name = os.getenv("LLM_MODEL", "deepseek-v4-pro")
        self.llm.api_key = os.getenv("LLM_API_KEY")
        self.llm.base_url = os.getenv("LLM_BASE_URL")
        self.llm.temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        self.llm.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4000"))

        self.embedding.provider = EmbeddingProvider(os.getenv("EMBEDDING_PROVIDER", "ollama"))
        self.embedding.model_name = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
        self.embedding.api_key = os.getenv("EMBEDDING_API_KEY") or self.llm.api_key
        self.embedding.base_url = os.getenv("EMBEDDING_BASE_URL") or self.llm.base_url
        self.embedding.local_device = os.getenv("EMBEDDING_DEVICE", "cpu")

        self.qdrant.host = os.getenv("QDRANT_HOST", "localhost")
        self.qdrant.port = int(os.getenv("QDRANT_PORT", "6333"))
        self.qdrant.api_key = os.getenv("QDRANT_API_KEY")

        self.database_url = os.getenv("DATABASE_URL", "") or f"sqlite:///{_DEFAULT_DB}"
        self.host = os.getenv("APP_HOST", "127.0.0.1")
        self.port = int(os.getenv("APP_PORT", "8000"))
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.jwt_secret = os.getenv("JWT_SECRET", "change-me")
        self.jwt_expire_days = int(os.getenv("JWT_EXPIRE_DAYS", "7"))
        self.storage_dir = os.getenv("STORAGE_DIR", "./data/uploads")
        self.retrieval_top_k = int(os.getenv("RETRIEVAL_TOP_K", "5"))
        self.retrieval_dense_threshold = float(os.getenv("RETRIEVAL_DENSE_THRESHOLD", "0.35"))
        self.chunk_size = int(os.getenv("CHUNK_SIZE", "800"))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "100"))


_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig()
    return _config
