import asyncio
import threading
import time
from datetime import datetime

from utils.logger import logger


def publish_chapter_job(schedule_id: int):
    """
    定时发布任务的执行函数
    在独立线程中运行异步事件循环
    """
    from database.connection import get_session
    from database.models import Schedule, Book, Account, PublishLog
    from chapters.tracker import chapter_tracker
    from utils.file_helpers import read_file_content, count_words
    from config import PUBLISH_DELAY_BETWEEN_CHAPTERS, MIN_CHAPTER_WORD_COUNT, ASYNC_BROWSER_TASK_TIMEOUT

    logger.info(f"===== 开始执行定时任务 #{schedule_id} =====")

    # 在线程中运行异步任务
    def run_async_job():
        asyncio.run(_async_publish_chapter(schedule_id))

    thread = threading.Thread(target=run_async_job, daemon=True)
    thread.start()
    thread.join(timeout=ASYNC_BROWSER_TASK_TIMEOUT)

    logger.info(f"===== 定时任务 #{schedule_id} 执行完毕 =====")


async def _async_publish_chapter(schedule_id: int):
    """异步发布章节"""
    from database.connection import get_session
    from database.models import Schedule, Book, Account, PublishLog, PendingTask
    from chapters.tracker import chapter_tracker
    from browser.manager import browser_manager
    from browser.fanqie.publisher import AsyncChapterPublisher
    from browser.fanqie.exceptions import SessionExpiredException
    from utils.file_helpers import read_file_content, count_words
    from config import PUBLISH_DELAY_BETWEEN_CHAPTERS, MIN_CHAPTER_WORD_COUNT

    db = get_session()
    try:
        schedule = db.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule or not schedule.is_active:
            logger.warning(f"定时任务 #{schedule_id} 不存在或已禁用")
            return

        book = db.query(Book).filter_by(id=schedule.book_id).first()
        if not book:
            logger.error(f"书籍 {schedule.book_id} 不存在")
            return

        account = db.query(Account).filter_by(id=book.account_id).first()
        if not account or account.status != "active":
            logger.warning(f"账号不可用 (状态: {account.status if account else 'None'})")
            return

        # 同步本地文件夹
        chapter_tracker.sync_chapters(book.id)

        # 获取待发布章节
        pending_chapters = chapter_tracker.get_next_pending_chapters(
            book.id, schedule.chapters_per_run
        )

        if not pending_chapters:
            logger.info(f"书籍 '{book.book_name}' 没有待发布的章节")
            schedule.last_run = datetime.now()
            db.commit()
            return

        # 检查是否已有该书的待发布任务
        existing_count = db.query(PendingTask).filter(
            PendingTask.book_id == book.id,
            PendingTask.status.in_(["pending", "publishing", "retry_pending"])
        ).count()

        # 如果有待发布任务，不需要再添加（已经在队列中）
        if existing_count > 0:
            logger.info(f"书籍 '{book.book_name}' 已有待发布任务，跳过添加")
            schedule.last_run = datetime.now()
            db.commit()
            return

        # 将章节添加到预发布队列，延迟1分钟
        from datetime import timedelta
        base_time = datetime.now() + timedelta(seconds=60)

        for i, chapter in enumerate(pending_chapters):
            scheduled_time = datetime.fromtimestamp(base_time.timestamp() + (i * 120))

            task = PendingTask(
                chapter_id=chapter.id,
                book_id=book.id,
                scheduled_time=scheduled_time,
                status="pending",
                notes=f"定时发布 (任务#{schedule_id})"
            )
            db.add(task)
            logger.info(f"定时任务添加预发布: {chapter.chapter_title} @ {scheduled_time}")

        db.commit()
        schedule.last_run = datetime.now()
        schedule.next_run = get_job_next_run(schedule.id)
        db.commit()
        logger.info(f"定时任务 #{schedule_id} 已添加 {len(pending_chapters)} 个章节到预发布队列")

    except Exception as e:
        logger.error(f"定时任务 #{schedule_id} 执行失败: {e}")
        db.rollback()
    finally:
        db.close()


def check_sessions_job():
    """定期检查所有活跃账号的Session状态"""
    from database.connection import get_session
    from database.models import Account

    logger.info("开始检查所有账号Session...")

    def run_async_check():
        asyncio.run(_async_check_sessions())

    thread = threading.Thread(target=run_async_check, daemon=True)
    thread.start()
    thread.join(timeout=120)


def cleanup_stale_chapters_job():
    """定期清理超时的 publishing 状态章节"""
    from chapters.tracker import chapter_tracker

    logger.info("开始清理超时的章节...")
    count = chapter_tracker.reset_stale_publishing_chapters(timeout_seconds=300)
    if count > 0:
        logger.info(f"已清理 {count} 个超时章节")


async def _async_check_sessions():
    """异步检查Session"""
    from database.connection import get_session
    from database.models import Account
    from browser.login import login_handler

    db = get_session()
    try:
        accounts = db.query(Account).filter_by(status="active").all()
        for account in accounts:
            try:
                is_valid = login_handler.check_session(account.id)
                if not is_valid:
                    account.status = "session_expired"
                    logger.warning(f"账号 '{account.name}' Session已过期")
                else:
                    account.last_login = datetime.now()
            except Exception as e:
                logger.error(f"检查账号 {account.id} Session时出错: {e}")
        db.commit()
    except Exception as e:
        logger.error(f"检查Session失败: {e}")
        db.rollback()
    finally:
        db.close()


def _log_publish(db, schedule_id, chapter_id, account_id, action, status, message, duration_ms):
    """记录发布日志"""
    from database.models import PublishLog
    try:
        log = PublishLog(
            schedule_id=schedule_id,
            chapter_id=chapter_id,
            account_id=account_id,
            action=action,
            status=status,
            message=message,
            duration_ms=duration_ms,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"记录日志失败: {e}")
        db.rollback()
