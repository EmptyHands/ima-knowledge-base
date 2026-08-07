"""ORM 模型测试 - 建表 / 关系 / 级联删除 / 唯一约束"""
import pytest
from sqlalchemy.exc import IntegrityError

from backend.core import database
from backend.core import config as config_module
from backend.models.database import User, KnowledgeBase, Document, Conversation, Message


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    config_module._config = None  # 清配置缓存,确保读到新 DATABASE_URL
    database.engine = None
    database.SessionLocal = None
    database.init_database()
    session = database.SessionLocal()
    yield session
    session.close()
    config_module._config = None
    database.engine = None
    database.SessionLocal = None


def _create_user(db, username="alice"):
    user = User(username=username, password_hash="hashed")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_create_entities_and_relations(db):
    user = _create_user(db)
    kb = KnowledgeBase(user_id=user.id, name="机器学习", description="论文库")
    db.add(kb)
    db.commit()
    db.refresh(kb)

    doc = Document(kb_id=kb.id, filename="transformer.pdf", file_path="/tmp/x.pdf",
                   file_size=1024, status="pending")
    conv = Conversation(kb_id=kb.id, user_id=user.id, title="新对话")
    db.add_all([doc, conv])
    db.commit()
    db.refresh(doc)
    db.refresh(conv)

    msg = Message(conversation_id=conv.id, role="user", content="你好",
                  citations_json=[{"index": 1, "doc_name": "a.pdf", "page": 2}])
    db.add(msg)
    db.commit()
    db.refresh(msg)

    assert user.knowledge_bases[0].id == kb.id
    assert kb.documents[0].filename == "transformer.pdf"
    assert kb.conversations[0].id == conv.id
    assert conv.messages[0].role == "user"
    assert msg.citations_json[0]["page"] == 2


def test_username_unique(db):
    _create_user(db, "bob")
    duplicate = User(username="bob", password_hash="hashed2")
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_cascade_delete_kb(db):
    user = _create_user(db)
    kb = KnowledgeBase(user_id=user.id, name="要删除的库")
    db.add(kb)
    db.commit()
    db.refresh(kb)

    doc = Document(kb_id=kb.id, filename="a.txt", file_path="/tmp/a.txt")
    conv = Conversation(kb_id=kb.id, user_id=user.id, title="会话")
    db.add_all([doc, conv])
    db.commit()
    db.refresh(conv)
    msg = Message(conversation_id=conv.id, role="assistant", content="回答")
    db.add(msg)
    db.commit()

    db.delete(kb)
    db.commit()

    assert db.query(Document).filter(Document.kb_id == kb.id).count() == 0
    assert db.query(Conversation).filter(Conversation.kb_id == kb.id).count() == 0
    assert db.query(Message).filter(Message.conversation_id == conv.id).count() == 0


def test_cascade_delete_user(db):
    user = _create_user(db)
    kb = KnowledgeBase(user_id=user.id, name="库")
    db.add(kb)
    db.commit()

    db.delete(user)
    db.commit()

    assert db.query(KnowledgeBase).filter(KnowledgeBase.user_id == user.id).count() == 0
