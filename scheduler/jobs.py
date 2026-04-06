import asyncio
import threading
import time
from datetime import datetime, timedelta

from utils.logger import logger


def publish_chapter_job(schedule_id: int):
    """
    定时发布任务的执行函数
    在独立线程中运行异步事件循环
    """
    from database.connection import safe_session
    from database.models import Schedule, Book, Account
    from chapters.tracker import chapter_tracker
    from config import ASYNC_BROWSER_TASK_TIMEOUT

    logger.info(f"===== 开始执行定时任务 #{schedule_id} =====")

    # 先获取必要的数据（同步操作）
    schedule_data = None
    with safe_session() as db:
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

        # 保存必要的数据
        schedule_data = {
            "schedule_id": schedule.id,
            "book_id": book.id,
            "account_id": account.id,
            "book_name": book.book_name,
            "target_value": schedule.target_value,
            "start_chapter": schedule.start_chapter or 1,
            "book_folder": book.local_folder,
        }
        logger.info(f"获取任务数据: 书籍={schedule_data['book_name']}, 章节={schedule_data['start_chapter']}")

    if not schedule_data:
        return

    # 在线程中运行异步任务
    def run_async_job():
        asyncio.run(_async_publish_chapter(schedule_data))

    thread = threading.Thread(target=run_async_job, daemon=True)
    thread.start()
    thread.join(timeout=ASYNC_BROWSER_TASK_TIMEOUT)

    logger.info(f"===== 定时任务 #{schedule_id} 执行完毕 =====")


async def _async_publish_chapter(schedule_data: dict):
    """异步发布章节"""
    from database.connection import safe_session
    from database.models import Book, Account, PendingTask, Schedule
    from chapters.tracker import chapter_tracker
    from browser.manager import browser_manager
    from browser.fanqie.publisher import AsyncChapterPublisher
    from browser.fanqie.exceptions import SessionExpiredException, PublishFailedException, SelectorNotFoundException
    from utils.file_helpers import read_file_content, count_words
    from config import PUBLISH_DELAY_BETWEEN_CHAPTERS, MIN_CHAPTER_WORD_COUNT

    book_id = schedule_data["book_id"]
    account_id = schedule_data["account_id"]
    target_value = schedule_data["target_value"]
    start_chapter = schedule_data["start_chapter"]
    schedule_id = schedule_data["schedule_id"]

    logger.info(f"开始发布: book_id={book_id}, account_id={account_id}")

    # 获取书籍锁
    book_lock = await browser_manager.async_get_book_lock(book_id)
    async with book_lock:
        account_lock = await browser_manager.async_get_account_lock(account_id)
        async with account_lock:
            context = await browser_manager._async_create_context_from_session(account_id)
            if not context:
                logger.error(f"无法获取账号 {account_id} 的浏览器Context")
                return

            page = await context.new_page()
            publisher = AsyncChapterPublisher(page)

            try:
                # 同步本地文件夹获取章节
                chapter_tracker.sync_chapters(book_id)

                # 获取待发布章节
                pending_chapters = chapter_tracker.get_next_pending_chapters(
                    book_id, target_value, start_chapter=start_chapter
                )

                if not pending_chapters:
                    logger.info(f"书籍没有待发布的章节")
                    # 更新最后运行时间
                    with safe_session() as db:
                        schedule = db.query(Schedule).filter_by(id=schedule_id).first()
                        if schedule:
                            schedule.last_run = datetime.now()
                    return

                logger.info(f"找到 {len(pending_chapters)} 个待发布章节")

                # 检查是否已有该书的待发布任务
                now = datetime.now()
                base_time = now + timedelta(seconds=60)

                with safe_session() as db:
                    existing_tasks = db.query(PendingTask).filter(
                        PendingTask.book_id == book_id,
                        PendingTask.status.in_(["pending", "publishing", "retry_pending"])
                    ).order_by(PendingTask.scheduled_time.desc()).first()

                    if existing_tasks:
                        latest_time = existing_tasks.scheduled_time
                        if (latest_time - base_time).total_seconds() > -180:
                            base_time = latest_time + timedelta(seconds=180)
                        logger.info(f"已有待发布任务，最近任务时间: {latest_time}，新任务从 {base_time} 开始")

                    # 添加待发布任务
                    for i, chapter in enumerate(pending_chapters):
                        scheduled_time = base_time + timedelta(seconds=i * 180)
                        task = PendingTask(
                            chapter_id=chapter.id,
                            book_id=book_id,
                            scheduled_time=scheduled_time,
                            status="pending",
                            notes=f"定时发布 (任务#{schedule_id})"
                        )
                        db.add(task)
                        logger.info(f"添加待发布: {chapter.chapter_title} @ {scheduled_time}")

                    # 更新最后运行时间
                    schedule = db.query(Schedule).filter_by(id=schedule_id).first()
                    if schedule:
                        schedule.last_run = datetime.now()

                logger.info(f"定时任务 #{schedule_id} 已添加 {len(pending_chapters)} 个章节到预发布队列")

            except Exception as e:
                logger.error(f"定时任务 #{schedule_id} 执行失败: {e}")
            finally:
                try:
                    await page.close()
                    await context.close()
                except Exception:
                    pass


def check_sessions_job():
    """定期检查所有活跃账号的Session状态"""
    from database.connection import safe_session
    from database.models import Account
    from browser.login import login_handler

    logger.info("开始检查所有账号Session...")

    try:
        with safe_session() as db:
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
    except Exception as e:
        logger.error(f"检查Session失败: {e}")


def cleanup_stale_chapters_job():
    """定期清理超时的 publishing 状态章节"""
    from chapters.tracker import chapter_tracker

    logger.info("开始清理超时的章节...")
    count = chapter_tracker.reset_stale_publishing_chapters(timeout_seconds=300)
    if count > 0:
        logger.info(f"已清理 {count} 个超时章节")
