import os
from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, Session

from config import DATABASE_URL

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=None,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        pool_pre_ping=True,
    )

SessionFactory = sessionmaker(bind=engine)
db_session = scoped_session(SessionFactory)


def init_db():
    """初始化数据库，创建所有表"""
    from database.models import Base
    Base.metadata.create_all(engine)


def get_session() -> Session:
    """获取数据库会话（调用者需负责关闭）"""
    return db_session()


@contextmanager
def safe_session(auto_commit: bool = True) -> Generator[Session, None, None]:
    """安全的数据库会话上下文管理器

    Args:
        auto_commit: 是否自动提交，默认True

    Usage:
        with safe_session() as db:
            book = db.query(Book).first()
            db.add(new_record)
        # 会话自动关闭，成功时自动提交

        with safe_session(auto_commit=False) as db:
            # 只读操作，不需要提交
            books = db.query(Book).all()
    """
    db = db_session()
    try:
        yield db
        if auto_commit:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """会话作用域上下文管理器（safe_session的别名，保持向后兼容）"""
    with safe_session() as db:
        yield db

