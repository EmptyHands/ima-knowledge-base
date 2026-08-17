"""DEV-015 记忆策略测试 - 摘要压缩"""
import pytest
from sqlalchemy import create_engine, text

from backend.core.database import migrate_memory_columns


def test_conversation_has_summary_columns():
    from backend.models.database import Conversation
    assert hasattr(Conversation, "summary")
    assert hasattr(Conversation, "summary_until_id")


def test_migrate_memory_columns_adds_missing_columns(tmp_path):
    """旧库(无新列)运行迁移后补齐两列"""
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY, title VARCHAR(200))"))
        conn.commit()
    migrate_memory_columns(engine)
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(conversations)"))}
    assert {"summary", "summary_until_id"} <= cols


def test_migrate_memory_columns_idempotent(tmp_path):
    """已有列的库重复迁移不报错"""
    engine = create_engine(f"sqlite:///{tmp_path/'new.db'}")
    from backend.core.database import Base
    Base.metadata.create_all(engine)
    migrate_memory_columns(engine)
    migrate_memory_columns(engine)
