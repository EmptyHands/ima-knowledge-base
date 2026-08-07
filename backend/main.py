"""ima-knowledge-base 主应用入口"""
import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.database import init_database  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ima-knowledge-base...")
    init_database()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down ima-knowledge-base...")


app = FastAPI(
    title="ima-knowledge-base API",
    description="智能知识库问答系统(Web 版 ima)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    qdrant_ok = False
    try:
        from backend.core.vector_store import get_vector_store
        store = get_vector_store()
        store.client.get_collection(store.collection_name)
        qdrant_ok = True
    except Exception as e:
        logger.warning(f"Qdrant health check failed: {e}")
    return {"status": "healthy", "qdrant": qdrant_ok}


@app.get("/")
async def index():
    return {"message": "ima-knowledge-base API", "docs": "/docs"}
