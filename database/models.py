from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        Index('ix_accounts_status', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True)
    status = Column(String(20), default="inactive")  # active / inactive / session_expired
    session_file = Column(Text, nullable=True)
    cookies = Column(Text, nullable=True)  # JSON 格式存储 cookie
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    books = relationship("Book", back_populates="account", cascade="all, delete-orphan")
    publish_logs = relationship("PublishLog", back_populates="account", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "status": self.status,
            "session_file": self.session_file,
            "has_cookies": bool(self.cookies),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        Index('ix_books_account_id', 'account_id'),
        Index('ix_books_status', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    fanqie_book_id = Column(String(50), nullable=True)
    book_name = Column(String(200), nullable=False)
    local_folder = Column(Text, nullable=False)
    chapter_pattern = Column(String(200), default=r"第(\d+)章\s+(.+)\.txt")
    book_status = Column(String(20), default="active")  # active / completed / hidden / signed / serializing
    status = Column(String(20), default="active")  # active / paused / completed
    created_at = Column(DateTime, default=datetime.now)

    account = relationship("Account", back_populates="books")
    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")
    schedules = relationship("Schedule", back_populates="book", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "fanqie_book_id": self.fanqie_book_id,
            "book_name": self.book_name,
            "local_folder": self.local_folder,
            "chapter_pattern": self.chapter_pattern,
            "book_status": self.book_status,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "account_name": self.account.name if self.account else None,
        }


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        Index('ix_chapters_book_id', 'book_id'),
        Index('ix_chapters_status', 'status'),
        Index('ix_chapters_book_status', 'book_id', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    chapter_title = Column(String(200), nullable=False)
    file_path = Column(Text, nullable=False)
    word_count = Column(Integer, default=0)
    status = Column(String(20), default="pending")  # pending / publishing / published / failed
    published_at = Column(DateTime, nullable=True)
    fanqie_chapter_id = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

    book = relationship("Book", back_populates="chapters")
    publish_logs = relationship("PublishLog", back_populates="chapter", cascade="all, delete-orphan")
    pending_tasks = relationship("PendingTask", back_populates="chapter", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "book_id": self.book_id,
            "chapter_number": self.chapter_number,
            "chapter_title": self.chapter_title,
            "file_path": self.file_path,
            "word_count": self.word_count,
            "status": self.status,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        Index('ix_schedules_book_id', 'book_id'),
        Index('ix_schedules_is_active', 'is_active'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    cron_expression = Column(String(100), nullable=False)  # 如 "0 8,20 * * *"
    publish_mode = Column(String(20), default="chapters")  # chapters / words
    target_value = Column(Integer, default=1)  # 章节数或字数
    is_active = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    book = relationship("Book", back_populates="schedules")
    publish_logs = relationship("PublishLog", back_populates="schedule")

    def to_dict(self):
        return {
            "id": self.id,
            "book_id": self.book_id,
            "cron_expression": self.cron_expression,
            "publish_mode": self.publish_mode,
            "target_value": self.target_value,
            "is_active": self.is_active,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "book_name": self.book.book_name if self.book else None,
            "account_name": self.book.account.name if self.book and self.book.account else None,
        }


class PublishLog(Base):
    __tablename__ = "publish_logs"
    __table_args__ = (
        Index('ix_publish_logs_chapter_id', 'chapter_id'),
        Index('ix_publish_logs_account_id', 'account_id'),
        Index('ix_publish_logs_schedule_id', 'schedule_id'),
        Index('ix_publish_logs_created_at', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    action = Column(String(20), nullable=False)  # publish / retry / manual_publish / skip_existed
    status = Column(String(20), nullable=False)  # success / failed / session_expired / skipped
    message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    schedule = relationship("Schedule", back_populates="publish_logs")
    chapter = relationship("Chapter", back_populates="publish_logs")
    account = relationship("Account", back_populates="publish_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "chapter_id": self.chapter_id,
            "account_id": self.account_id,
            "action": self.action,
            "status": self.status,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "chapter_title": self.chapter.chapter_title if self.chapter else None,
            "account_name": self.account.name if self.account else None,
            "book_name": self.chapter.book.book_name if self.chapter and self.chapter.book else None,
        }


class PendingTask(Base):
    """待发布任务"""
    __tablename__ = "pending_tasks"
    __table_args__ = (
        Index('ix_pending_tasks_status_scheduled', 'status', 'scheduled_time'),
        Index('ix_pending_tasks_chapter_id', 'chapter_id'),
        Index('ix_pending_tasks_book_id', 'book_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)  # 冗余字段，方便查询
    scheduled_time = Column(DateTime, nullable=False)  # 计划发布时间
    status = Column(String(20), default="pending")  # pending / publishing / published / cancelled / retry_pending
    notes = Column(Text, nullable=True)  # 备注
    retry_count = Column(Integer, default=0)  # 重试次数
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    chapter = relationship("Chapter")
    book = relationship("Book")

    def to_dict(self):
        return {
            "id": self.id,
            "chapter_id": self.chapter_id,
            "book_id": self.book_id,
            "scheduled_time": self.scheduled_time.isoformat() if self.scheduled_time else None,
            "status": self.status,
            "notes": self.notes,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            # 关联信息
            "chapter_title": self.chapter.chapter_title if self.chapter else None,
            "chapter_number": self.chapter.chapter_number if self.chapter else None,
            "book_name": self.book.book_name if self.book else (self.chapter.book.book_name if self.chapter and self.chapter.book else None),
            "account_id": self.book.account_id if self.book else (self.chapter.book.account_id if self.chapter and self.chapter.book else None),
            "account_name": self.book.account.name if self.book and self.book.account else (self.chapter.book.account.name if self.chapter and self.chapter.book and self.chapter.book.account else None),
        }


class FeishuConfig(Base):
    """飞书配置"""
    __tablename__ = "feishu_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    app_id = Column(String(100), nullable=True)
    app_secret = Column(String(200), nullable=True)
    webhook_url = Column(Text, nullable=True)
    enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "app_id": self.app_id,
            "app_secret": "****" if self.app_secret else None,
            "webhook_url": self.webhook_url,
            "enabled": self.enabled,
        }
