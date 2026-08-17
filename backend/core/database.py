"""智能知识库问答系统 数据库管理模块"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import get_config

engine = None
SessionLocal = None
Base = declarative_base()


def init_database():
    global engine, SessionLocal
    config = get_config()
    connect_args = {}
    if "sqlite" in config.database_url:
        connect_args["check_same_thread"] = False
    engine = create_engine(config.database_url, connect_args=connect_args, echo=config.debug)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    from backend.models.database import User, KnowledgeBase, Document, Conversation, Message  # noqa
    Base.metadata.create_all(bind=engine)


def migrate_memory_columns(engine=None):
    """轻量列迁移: 旧库 conversations 表补 summary / summary_until_id 列 (DEV-015)"""
    from sqlalchemy import text
    target = engine or globals().get("engine")
    if target is None:
        return
    with target.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(conversations)"))}
        if "summary" not in cols:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN summary TEXT"))
        if "summary_until_id" not in cols:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN summary_until_id VARCHAR(36)"))
        conn.commit()


def get_db():
    if SessionLocal is None:
        init_database()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session():
    if SessionLocal is None:
        init_database()
    return SessionLocal()
