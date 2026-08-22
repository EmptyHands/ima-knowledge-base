"""DEV-019: 多实例共享 SQLite — WAL 模式 + busy timeout"""
import sqlalchemy
import backend.core.database as database_module


def test_sqlite_engine_wal_mode(tmp_path, monkeypatch):
    db_path = tmp_path / "wal_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import backend.core.config as config_module
    config_module._config = None
    database_module.engine = None
    database_module.SessionLocal = None
    from backend.core.database import init_database
    init_database()
    with database_module.engine.connect() as conn:
        mode = conn.execute(sqlalchemy.text("PRAGMA journal_mode")).scalar()
        assert mode == "wal"
