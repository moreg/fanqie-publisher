#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
待发布任务调度器
"""
import asyncio
import threading
import time
import random
from datetime import datetime, timedelta
from typing import Optional, Callable, List

from sqlalchemy.orm import Session
from database.connection import safe_session
from database.models import PendingTask, Chapter, Book, Account, PublishLog, Schedule, PublishConfirm, SystemConfig
from utils.logger import logger
from utils.feishu import get_feishu_notifier
from chapters.tracker import chapter_tracker
from browser.manager import browser_manager
from utils.file_helpers import read_file_content, count_words
from config import MIN_CHAPTER_WORD_COUNT

TASK_EXPIRE_MINUTES = 30
MAX_RETRIES = 2


class TaskScheduler:
    """待发布任务调度器"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._check_interval = 10
        self._on_task_ready: Optional[Callable] = None

        # 加载飞书配置
        self._load_feishu_config()

    def _load_feishu_config(self):
        """加载飞书配置"""
        try:
            from database.models import FeishuConfig as FeishuConfigModel
            from utils.feishu import FeishuConfig, get_feishu_notifier

            with safe_session() as db:
                config = db.query(FeishuConfigModel).first()
                if config:
                    notifier = get_feishu_notifier()
                    notifier.set_config(FeishuConfig(
                        app_id=config.app_id or "",
                        app_secret=config.app_secret or "",
                        webhook_url=config.webhook_url or "",
                        enabled=config.enabled
                    ))
                    logger.info(f"飞书配置已加载: enabled={config.enabled}")
        except Exception as e:
            logger.debug(f"加载飞书配置失败: {e}")

    def _get_confirm_delay_minutes(self) -> int:
        """获取发布确认延迟时间（分钟）"""
        try:
            with safe_session() as db:
                config = db.query(SystemConfig).filter_by(key="publish_confirm_delay").first()
                if config and config.value:
                    return int(config.value)
        except Exception as e:
            logger.debug(f"获取确认延迟失败: {e}")
        return 20  # 默认20分钟

    def _add_publish_confirm(self, book_id: int, chapter_id: int, fanqie_book_id: str, chapter_title: str):
        """添加待确认的发布记录"""
        try:
            delay_minutes = self._get_confirm_delay_minutes()
            confirm_after = datetime.now() + timedelta(minutes=delay_minutes)

            with safe_session() as db:
                confirm = PublishConfirm(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    fanqie_book_id=fanqie_book_id,
                    chapter_title=chapter_title,
                    status="pending",
                    confirm_after=confirm_after
                )
                db.add(confirm)
                logger.info(f"添加发布确认记录: {chapter_title}, 确认时间: {confirm_after}")
        except Exception as e:
            logger.error(f"添加发布确认记录失败: {e}")

    def start(self):
        """启动调度器"""
        if self._running:
            logger.warning("调度器已在运行")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("待发布任务调度器已启动")

    def stop(self):
        """停止调度器"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("待发布任务调度器已停止")

    def set_task_callback(self, callback: Callable):
        """设置任务就绪时的回调函数"""
        self._on_task_ready = callback

    def _run_loop(self):
        """主循环"""
        while self._running:
            try:
                self._check_pending_tasks()
            except (OSError, IOError) as e:
                logger.error(f"检查待发任务时发生IO错误: {e}")
            except Exception as e:
                logger.error(f"检查待发任务失败: {e}")

            time.sleep(self._check_interval)

    def _check_pending_tasks(self):
        """检查待发任务"""
        now = datetime.now()

        self._handle_expired_tasks(now)

        while True:
            task_data = self._claim_next_task(now)
            if not task_data:
                break

            task_id, chapter_id, book_id = task_data
            success, result = self._validate_task_data(task_id, chapter_id, book_id)

            if not success:
                continue

            chapter_id, book_id, account_id, fanqie_book_id, file_path = result
            self._execute_publish(task_id, chapter_id, book_id, account_id, fanqie_book_id, file_path)

    def _handle_expired_tasks(self, now: datetime):
        """处理过期任务 - 标记为失败而非删除"""
        expired_threshold = now - timedelta(minutes=TASK_EXPIRE_MINUTES)

        with safe_session() as db:
            expired_tasks = db.query(PendingTask).filter(
                PendingTask.status == "pending",
                PendingTask.scheduled_time < expired_threshold
            ).all()

            for task in expired_tasks:
                chapter = db.query(Chapter).filter_by(id=task.chapter_id).first()
                title = chapter.chapter_title if chapter else f"章节{task.chapter_id}"
                logger.warning(f"任务已过期超过{TASK_EXPIRE_MINUTES}分钟，标记为失败: ID={task.id}, 章节={title}")
                task.status = "failed"
                task.notes = f"任务过期（超过{TASK_EXPIRE_MINUTES}分钟未执行）"

    def _claim_next_task(self, now: datetime) -> Optional[tuple]:
        """声明下一个待执行任务，返回 (task_id, chapter_id, book_id) 或 None"""
        with safe_session() as db:
            task = db.query(PendingTask).filter(
                PendingTask.status == "pending",
                PendingTask.scheduled_time <= now
            ).first()

            if not task:
                return None

            chapter = db.query(Chapter).filter_by(id=task.chapter_id).first()
            if chapter:
                blocking_task = db.query(PendingTask).join(Chapter).filter(
                    PendingTask.book_id == chapter.book_id,
                    PendingTask.status.in_(["pending", "publishing"]),
                    Chapter.chapter_number < chapter.chapter_number
                ).first()

                if blocking_task:
                    blocking_chapter = db.query(Chapter).filter_by(id=blocking_task.chapter_id).first()
                    blocking_title = blocking_chapter.chapter_title if blocking_chapter else f"章节{blocking_task.chapter_id}"
                    logger.info(f"任务 {task.id} 被章节 '{blocking_title}' 阻塞，等待串行发布")
                    return None

            updated = db.query(PendingTask).filter(
                PendingTask.id == task.id,
                PendingTask.status == "pending"
            ).update({"status": "publishing"})

            if updated == 0:
                return None

            chapter_title = task.chapter.chapter_title if task.chapter else f"章节{task.chapter_id}"
            logger.info(f"声明待发任务: ID={task.id}, 章节={chapter_title}, 重试次数={task.retry_count}")

            return (task.id, task.chapter_id, task.book_id)

    def _validate_task_data(self, task_id: int, chapter_id: int, book_id: int) -> tuple:
        """验证任务数据，返回 (success, data)"""
        with safe_session(auto_commit=False) as db:
            try:
                chapter = db.query(Chapter).filter_by(id=chapter_id).first()
                if not chapter:
                    self._mark_task_failed(task_id, "章节不存在", chapter_id)
                    return (False, None)

                book = db.query(Book).filter_by(id=book_id).first()
                if not book:
                    self._mark_task_failed(task_id, "书籍不存在", chapter_id)
                    return (False, None)

                account = db.query(Account).filter_by(id=book.account_id).first()
                if not account or account.status != "active":
                    self._mark_task_failed(task_id, "账号不可用", chapter_id)
                    return (False, None)

                if not book.fanqie_book_id:
                    self._mark_task_failed(task_id, "未设置番茄书籍ID", chapter_id)
                    return (False, None)

                return (True, (chapter.id, book.id, account.id, book.fanqie_book_id, chapter.file_path))

            except (OSError, IOError) as e:
                logger.error(f"获取任务关联数据时发生IO错误: {e}")
                self._mark_task_failed(task_id, f"获取数据失败: {e}", chapter_id)
                return (False, None)

    def _execute_publish(self, task_id: int, chapter_id: int, book_id: int, account_id: int, fanqie_book_id: str, file_path: str):
        """执行章节发布"""
        try:
            browser_manager._run_async(
                self._async_publish_chapter(task_id, chapter_id, account_id, fanqie_book_id, file_path)
            )
        except Exception as e:
            logger.error(f"发布执行失败: {e}")
            self._mark_task_failed(task_id, f"发布执行失败: {e}", chapter_id)

    async def _async_publish_chapter(self, task_id: int, chapter_id: int, account_id: int, fanqie_book_id: str, file_path: str):
        """异步发布章节"""
        from browser.fanqie.publisher import AsyncChapterPublisher
        from browser.fanqie.exceptions import SessionExpiredException, PublishFailedException, SelectorNotFoundException

        logger.info(f"异步发布章节: chapter_id={chapter_id}, account_id={account_id}")

        account_lock = await browser_manager.async_get_account_lock(account_id)
        async with account_lock:
            context = await browser_manager._async_create_context_from_session(account_id)
            if not context:
                logger.error(f"无法获取账号 {account_id} 的浏览器Context")
                self._mark_account_expired(account_id)
                self._mark_task_failed(task_id, "无法获取浏览器上下文", chapter_id)
                return

            page = await context.new_page()
            publisher = AsyncChapterPublisher(page)

            try:
                with safe_session(auto_commit=False) as db:
                    chapter = db.query(Chapter).filter_by(id=chapter_id).first()
                    chapter_title = chapter.chapter_title if chapter else "未知章节"
                    chapter_number = chapter.chapter_number if chapter else 1
                    book_name = chapter.book.book_name if chapter and chapter.book else "未知书籍"

                # 构造完整标题（包含"第X章"前缀）供番茄网站使用
                full_chapter_title = f"第{chapter_number}章 {chapter_title}"

                chapter_tracker.mark_chapter_publishing(chapter_id)

                try:
                    content = read_file_content(file_path)
                except (OSError, IOError, UnicodeDecodeError) as e:
                    chapter_tracker.mark_chapter_failed(chapter_id, f"读取文件失败: {e}")
                    self._log_publish(None, task_id, chapter_id, account_id, "scheduled", "failed", f"读取文件失败: {e}", 0)
                    self._mark_task_failed(task_id, f"读取文件失败: {e}", chapter_id)
                    return

                word_count = count_words(content)
                if word_count < MIN_CHAPTER_WORD_COUNT:
                    chapter_tracker.mark_chapter_failed(chapter_id, f"字数不足: {word_count}")
                    self._log_publish(None, task_id, chapter_id, account_id, "scheduled", "failed", f"字数不足: {word_count}", 0)
                    self._mark_task_failed(task_id, f"字数不足", chapter_id)
                    return

                try:
                    result = await publisher.publish_chapter(
                        fanqie_book_id=fanqie_book_id,
                        chapter_title=full_chapter_title,
                        chapter_content=content,
                    )
                except SessionExpiredException:
                    logger.error(f"账号 {account_id} Session过期")
                    self._mark_account_expired(account_id)
                    self._log_publish(None, task_id, chapter_id, account_id, "scheduled", "session_expired", "Session过期", 0)
                    self._mark_task_failed(task_id, "Session过期", chapter_id)
                    return
                except (PublishFailedException, SelectorNotFoundException) as e:
                    logger.error(f"发布失败: {e}")
                    self._log_publish(None, task_id, chapter_id, account_id, "scheduled", "failed", str(e), 0)
                    self._mark_task_failed(task_id, str(e), chapter_id)
                    return

                with safe_session() as db:
                    task = db.query(PendingTask).filter_by(id=task_id).first()
                    if result.success:
                        if result.already_exists:
                            chapter_tracker.mark_chapter_published(chapter_id, result.fanqie_chapter_id)
                            task.status = "published"
                            task.notes = "章节已存在于番茄网站"
                            self._log_publish(db, task_id, chapter_id, account_id, "scheduled", "skipped", "章节已存在于番茄网站，同步标记为已发布", result.duration_ms)
                            logger.info(f"章节 '{full_chapter_title}' 已存在于番茄网站，标记为已发布")
                            # 发送飞书通知
                            self._send_feishu_notification(book_name, full_chapter_title, True)
                            # 自动更新起始章节
                            self._update_schedule_start_chapter(book_id, chapter_number)
                            # 添加发布确认记录
                            self._add_publish_confirm(book_id, chapter_id, fanqie_book_id, full_chapter_title)
                        else:
                            chapter_tracker.mark_chapter_published(chapter_id, result.fanqie_chapter_id)
                            task.status = "published"
                            task.notes = "发布成功"
                            self._log_publish(db, task_id, chapter_id, account_id, "scheduled", "success", result.message, result.duration_ms)
                            logger.info(f"章节发布成功: {full_chapter_title}")
                            # 发送飞书通知
                            self._send_feishu_notification(book_name, full_chapter_title, True)
                            # 自动更新起始章节
                            self._update_schedule_start_chapter(book_id, chapter_number)
                            # 添加发布确认记录
                            self._add_publish_confirm(book_id, chapter_id, fanqie_book_id, full_chapter_title)
                    else:
                        chapter_tracker.mark_chapter_failed(chapter_id, result.message)
                        self._log_publish(db, task_id, chapter_id, account_id, "scheduled", "failed", result.message, result.duration_ms)
                        logger.error(f"章节发布失败: {full_chapter_title} - {result.message}")
                        self._mark_task_failed(task_id, result.message, chapter_id)
                        # 发送飞书通知
                        self._send_feishu_notification(book_name, full_chapter_title, False, result.message)

            except asyncio.TimeoutError:
                logger.error(f"发布超时: chapter_id={chapter_id}")
                self._mark_task_failed(task_id, "发布超时", chapter_id)
            except Exception as e:
                logger.error(f"发布异常: {e}")
                self._mark_task_failed(task_id, str(e), chapter_id)
            finally:
                try:
                    await page.close()
                    await context.close()
                except Exception:
                    pass

    def _mark_account_expired(self, account_id: int):
        """标记账号过期"""
        with safe_session() as db:
            account = db.query(Account).filter_by(id=account_id).first()
            if account:
                account.status = "session_expired"

    def _mark_task_failed(self, task_id: int, error_message: str, chapter_id: int = None):
        """标记任务失败并安排重试"""
        with safe_session() as db:
            task = db.query(PendingTask).filter_by(id=task_id).first()
            if not task:
                logger.error(f"任务 {task_id} 不存在")
                return

            if chapter_id is None:
                chapter_id = task.chapter_id

            book_id = task.book_id
            if not book_id:
                chapter = db.query(Chapter).filter_by(id=chapter_id).first()
                if chapter:
                    book_id = chapter.book_id

            if task.retry_count < MAX_RETRIES:
                delay_seconds = random.randint(600, 1200)
                next_time = datetime.now() + timedelta(seconds=delay_seconds)

                retry_task = PendingTask(
                    chapter_id=chapter_id,
                    book_id=book_id,
                    scheduled_time=next_time,
                    status="pending",
                    notes=f"第{task.retry_count + 1}次重试: {error_message[:50]}",
                    retry_count=task.retry_count + 1
                )
                db.add(retry_task)

                task.status = "retry_pending"
                task.notes = f"已安排第{task.retry_count + 1}次重试 @ {next_time}"

                logger.info(f"任务 {task_id} 失败，已安排第{task.retry_count + 1}次重试 @ {next_time}")
            else:
                task.status = "failed"
                task.notes = f"重试{MAX_RETRIES}次后仍失败: {error_message[:100]}"
                logger.warning(f"任务 {task_id} 重试{MAX_RETRIES}次后仍失败，标记为失败")

                self._cancel_following_tasks(db, task, chapter_id, error_message)

                # 发送飞书通知（重试失败）
                self._send_feishu_notification(None, None, False, error_message)

    def _send_feishu_notification(self, book_name: str, chapter_title: str, success: bool, error_message: str = ""):
        """发送飞书通知"""
        try:
            notifier = get_feishu_notifier()
            if not notifier.is_enabled():
                return

            if success:
                notifier.send_publish_success(
                    book_name=book_name or "未知书籍",
                    chapter_title=chapter_title or "未知章节"
                )
            else:
                notifier.send_publish_failed(
                    book_name=book_name or "未知书籍",
                    chapter_title=chapter_title or "未知章节",
                    error_message=error_message
                )
        except Exception as e:
            logger.error(f"发送飞书通知失败: {e}")

    def _update_schedule_start_chapter(self, book_id: int, published_chapter_number: int):
        """自动更新定时任务的起始章节为下一个待发布章节"""
        with safe_session() as db:
            schedules = db.query(Schedule).filter_by(book_id=book_id, is_active=True).all()
            if not schedules:
                return

            schedule = schedules[0]

            # 查询下一个待发布的章节
            next_chapter = db.query(Chapter).filter(
                Chapter.book_id == book_id,
                Chapter.status == "pending",
                Chapter.chapter_number > published_chapter_number
            ).order_by(Chapter.chapter_number).first()

            if next_chapter:
                old_start = schedule.start_chapter
                schedule.start_chapter = next_chapter.chapter_number
                logger.info(f"定时任务起始章节自动更新: {old_start} -> {next_chapter.chapter_number} (已发布第{published_chapter_number}章)")
            else:
                logger.info(f"所有章节已发布完毕，无需更新起始章节")

    def _cancel_following_tasks(self, db: Session, failed_task: PendingTask, failed_chapter_id: int, error_message: str):
        """取消同一本书中后续章节的任务（串行发布规则）"""
        try:
            failed_chapter = db.query(Chapter).filter_by(id=failed_chapter_id).first()
            if not failed_chapter:
                return

            following_tasks = db.query(PendingTask).join(Chapter).filter(
                PendingTask.book_id == failed_chapter.book_id,
                PendingTask.status.in_(["pending", "retry_pending"]),
                Chapter.chapter_number > failed_chapter.chapter_number
            ).all()

            if following_tasks:
                for task in following_tasks:
                    task.status = "cancelled"
                    task.notes = f"因章节'{failed_chapter.chapter_title}'发布失败而取消: {error_message[:50]}"
                    logger.info(f"因章节'{failed_chapter.chapter_title}'失败，取消后续任务: ID={task.id}")

                logger.info(f"共取消 {len(following_tasks)} 个后续章节任务")
        except Exception as e:
            logger.error(f"取消后续任务时出错: {e}")

    def _log_publish(self, db_injected: Optional[Session], task_id: int, chapter_id: int, account_id: int, action: str, status: str, message: str, duration_ms: int):
        """记录发布日志"""
        if db_injected is None:
            with safe_session() as db:
                log = PublishLog(
                    schedule_id=task_id,
                    chapter_id=chapter_id,
                    account_id=account_id,
                    action=action,
                    status=status,
                    message=message,
                    duration_ms=duration_ms,
                )
                db.add(log)
        else:
            log = PublishLog(
                schedule_id=task_id,
                chapter_id=chapter_id,
                account_id=account_id,
                action=action,
                status=status,
                message=message,
                duration_ms=duration_ms,
            )
            db_injected.add(log)

    def add_task_with_delay(self, chapter_ids: List[int], start_time: datetime, delay_range: tuple = (60, 120)) -> bool:
        """
        添加多个章节任务，自动错开发布时间

        Args:
            chapter_ids: 章节ID列表（按发布顺序）
            start_time: 起始发布时间
            delay_range: 延迟范围(秒)，默认60-120秒(1-2分钟)
        """
        with safe_session() as db:
            current_time = start_time
            first_book_id = None

            for i, chapter_id in enumerate(chapter_ids):
                if i > 0:
                    delay = random.randint(*delay_range)
                    current_time = datetime.fromtimestamp(current_time.timestamp() + delay)

                chapter = db.query(Chapter).filter_by(id=chapter_id).first()
                book_id = chapter.book_id if chapter else None
                if first_book_id is None:
                    first_book_id = book_id

                task = PendingTask(
                    chapter_id=chapter_id,
                    book_id=book_id or first_book_id,
                    scheduled_time=current_time,
                    status="pending"
                )
                db.add(task)

                chapter_title = chapter.chapter_title if chapter else f"章节{chapter_id}"
                logger.info(f"添加待发任务: {chapter_title} @ {current_time}")

            return True

    def get_next_task_time(self) -> Optional[datetime]:
        """获取下一个待发任务的时间"""
        with safe_session(auto_commit=False) as db:
            task = db.query(PendingTask).filter_by(status="pending").order_by(
                PendingTask.scheduled_time
            ).first()
            return task.scheduled_time if task else None


task_scheduler = TaskScheduler()
