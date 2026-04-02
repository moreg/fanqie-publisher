#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发布确认检查器
"""
import threading
import time
from datetime import datetime
from typing import Optional

from database.connection import safe_session
from database.models import PublishConfirm, Account
from utils.logger import logger
from browser.manager import browser_manager


class PublishConfirmChecker:
    """发布确认检查器"""

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
        self._check_interval = 60  # 每分钟检查一次

    def start(self):
        """启动确认检查器"""
        if self._running:
            logger.warning("确认检查器已在运行")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("发布确认检查器已启动")

    def stop(self):
        """停止确认检查器"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("发布确认检查器已停止")

    def _run_loop(self):
        """主循环"""
        while self._running:
            try:
                self._check_pending_confirms()
            except Exception as e:
                logger.error(f"检查发布确认失败: {e}")

            time.sleep(self._check_interval)

    def _check_pending_confirms(self):
        """检查待确认的发布记录"""
        now = datetime.now()

        with safe_session() as db:
            # 查询到期的待确认记录
            pending_confirms = db.query(PublishConfirm).filter(
                PublishConfirm.status == "pending",
                PublishConfirm.confirm_after <= now
            ).order_by(PublishConfirm.confirm_after).limit(10).all()

            if not pending_confirms:
                return

            logger.info(f"发现 {len(pending_confirms)} 条待确认记录")

            for confirm in pending_confirms:
                self._process_confirm(db, confirm)

    def _process_confirm(self, db, confirm: PublishConfirm):
        """处理单个确认记录"""
        try:
            # 获取账号信息
            account = db.query(Account).filter_by(id=confirm.book.account_id if confirm.book else None).first()
            if not account:
                confirm.status = "failed"
                confirm.error_message = "找不到关联账号"
                logger.error(f"确认失败: {confirm.chapter_title}, 错误: 找不到关联账号")
                return

            # 检查账号是否可用
            if account.status != "active":
                confirm.status = "failed"
                confirm.error_message = f"账号不可用: {account.status}"
                logger.error(f"确认失败: {confirm.chapter_title}, 错误: 账号不可用")
                return

            # 使用浏览器检查章节是否存在
            browser_manager._run_async(
                self._async_check_chapter(confirm, account.id)
            )

        except Exception as e:
            logger.error(f"处理确认记录失败: {e}")
            confirm.status = "failed"
            confirm.error_message = str(e)

    async def _async_check_chapter(self, confirm: PublishConfirm, account_id: int):
        """异步检查章节是否存在"""
        from browser.fanqie.publisher import AsyncChapterPublisher

        account_lock = await browser_manager.async_get_account_lock(account_id)
        async with account_lock:
            context = await browser_manager._async_create_context_from_session(account_id)
            if not context:
                self._mark_confirm_failed(confirm.id, "无法获取浏览器上下文")
                return

            page = await context.new_page()
            try:
                publisher = AsyncChapterPublisher(page)

                # 检查章节是否存在
                exists, chapter_id = await publisher.check_chapter_exists(
                    confirm.fanqie_book_id,
                    confirm.chapter_title
                )

                if exists:
                    self._mark_confirm_success(confirm.id)
                    logger.info(f"发布确认成功: {confirm.chapter_title}")
                else:
                    self._mark_confirm_failed(confirm.id, "章节在番茄网站上未找到")
                    logger.warning(f"发布确认失败: {confirm.chapter_title}, 章节未找到")

            except Exception as e:
                self._mark_confirm_failed(confirm.id, str(e))
                logger.error(f"确认检查异常: {confirm.chapter_title}, {e}")
            finally:
                try:
                    await page.close()
                    await context.close()
                except Exception:
                    pass

    def _mark_confirm_success(self, confirm_id: int):
        """标记确认成功"""
        with safe_session() as db:
            confirm = db.query(PublishConfirm).filter_by(id=confirm_id).first()
            if confirm:
                confirm.status = "confirmed"
                confirm.confirmed_at = datetime.now()
                logger.info(f"确认成功: {confirm.chapter_title}")

    def _mark_confirm_failed(self, confirm_id: int, error_message: str, max_retries: int = 3):
        """标记确认失败并处理重试"""
        with safe_session() as db:
            confirm = db.query(PublishConfirm).filter_by(id=confirm_id).first()
            if not confirm:
                return

            confirm.retry_count += 1

            if confirm.retry_count < max_retries:
                # 安排重试，等待5分钟后再检查
                from datetime import timedelta
                confirm.confirm_after = datetime.now() + timedelta(minutes=5)
                logger.info(f"确认失败，将重试 (第{confirm.retry_count}次): {confirm.chapter_title}")
            else:
                confirm.status = "failed"
                confirm.error_message = error_message
                confirm.confirmed_at = datetime.now()
                logger.error(f"确认失败 (已重试{confirm.retry_count}次): {confirm.chapter_title}, 错误: {error_message}")

                # 发送飞书通知
                self._send_confirm_failed_notification(confirm)

    def _send_confirm_failed_notification(self, confirm: PublishConfirm):
        """发送确认失败通知"""
        try:
            from utils.feishu import get_feishu_notifier
            notifier = get_feishu_notifier()
            if notifier.is_enabled():
                book_name = confirm.book.book_name if confirm.book else "未知书籍"
                notifier.send_publish_failed(
                    book_name=book_name,
                    chapter_title=confirm.chapter_title,
                    error_message=f"发布确认失败: {confirm.error_message}"
                )
        except Exception as e:
            logger.error(f"发送确认失败通知失败: {e}")

    def get_pending_count(self) -> int:
        """获取待确认数量"""
        with safe_session() as db:
            return db.query(PublishConfirm).filter_by(status="pending").count()


publish_confirm_checker = PublishConfirmChecker()
