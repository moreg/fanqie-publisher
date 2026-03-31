#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
番茄小说自动发布器 - 交互式命令行界面
"""
import os
import sys
import asyncio
import signal
import re
from cmd import Cmd
from typing import Optional, List

from database.connection import get_session, init_db
from database.models import Account, Book, Chapter, PublishLog, Schedule, PendingTask
from browser.manager import browser_manager
from browser.fanqie.exceptions import SessionExpiredException
from chapters.scanner import ChapterScanner
from chapters.tracker import chapter_tracker
from scheduler.engine import init_scheduler, shutdown_scheduler, add_session_check_job, add_cleanup_job
from scheduler.recovery import recover_missed_schedules
from utils.logger import logger
from utils.file_helpers import read_file_content
from config import MIN_CHAPTER_WORD_COUNT, PUBLISH_DELAY_BETWEEN_CHAPTERS, PUBLISH_DELAY_MIN, PUBLISH_DELAY_MAX


class FanqieCLI(Cmd):
    """番茄小说命令行工具"""

    prompt = "(番茄) >>> "
    intro = """
╔═══════════════════════════════════════════════════════╗
║        番茄小说自动发布器 v1.0                          ║
║═══════════════════════════════════════════════════════╝
输入 help 查看可用命令
    """

    def __init__(self):
        super().__init__()
        self.current_account_id: Optional[int] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def run(self):
        """运行CLI"""
        try:
            self.cmdloop()
        except KeyboardInterrupt:
            print("\n\n退出中...")
            self.do_exit(None)

    # ==================== 账号管理 ====================

    def do_accounts(self, arg):
        """accounts - 查看所有账号"""
        db = get_session()
        try:
            accounts = db.query(Account).all()
            if not accounts:
                print("\n暂无账号，请先登录")
                return

            print("\n{:<5} {:<15} {:<12} {:<20}".format(
                "ID", "名称", "状态", "最后登录"))
            print("-" * 55)
            for acc in accounts:
                print("{:<5} {:<15} {:<12} {:<20}".format(
                    acc.id,
                    acc.name[:12],
                    acc.status,
                    str(acc.last_login)[:19] if acc.last_login else "从未登录"
                ))
        finally:
            db.close()

    def do_login(self, arg):
        """login <账号ID> - 登录指定账号"""
        if not arg:
            print("用法: login <账号ID>")
            return

        try:
            account_id = int(arg)
        except ValueError:
            print("账号ID必须是数字")
            return

        db = get_session()
        try:
            account = db.query(Account).filter_by(id=account_id).first()
            if not account:
                print(f"账号 {account_id} 不存在")
                return

            self.current_account_id = account_id
            print(f"正在启动浏览器登录，请完成验证...")

            # 启动异步登录
            async def _do_login():
                from browser.fanqie.login import login_with_browser
                success = await login_with_browser(account_id)
                if success:
                    print("登录成功!")
                    db = get_session()
                    try:
                        acc = db.query(Account).filter_by(id=account_id).first()
                        if acc:
                            print(f"账号 '{acc.name}' 状态: {acc.status}")
                    finally:
                        db.close()
                else:
                    print("登录失败或超时")

            self._run_async(_do_login())
        finally:
            db.close()

    def do_account_status(self, arg):
        """account_status <账号ID> - 检查账号Session状态"""
        if not arg:
            if not self.current_account_id:
                print("请先指定账号: use <账号ID>")
                return
            account_id = self.current_account_id
        else:
            try:
                account_id = int(arg)
            except ValueError:
                print("账号ID必须是数字")
                return

        db = get_session()
        try:
            account = db.query(Account).filter_by(id=account_id).first()
            if not account:
                print(f"账号 {account_id} 不存在")
                return

            print(f"\n账号信息:")
            print(f"  名称: {account.name}")
            print(f"  状态: {account.status}")
            print(f"  Session: {'有效' if account.status == 'active' else '无效/过期'}")

            # 检查Session文件
            session_file = browser_manager._get_session_file(account_id)
            print(f"  Session文件: {session_file}")
            print(f"  文件存在: {os.path.exists(session_file)}")
        finally:
            db.close()

    def do_use(self, arg):
        """use <账号ID> - 设置当前使用的账号"""
        if not arg:
            print("用法: use <账号ID>")
            return

        try:
            account_id = int(arg)
        except ValueError:
            print("账号ID必须是数字")
            return

        db = get_session()
        try:
            account = db.query(Account).filter_by(id=account_id).first()
            if not account:
                print(f"账号 {account_id} 不存在")
                return

            self.current_account_id = account_id
            print(f"已切换到账号: {account.name}")
        finally:
            db.close()

    # ==================== 书籍管理 ====================

    def do_books(self, arg):
        """books - 查看所有书籍"""
        db = get_session()
        try:
            books = db.query(Book).all()
            if not books:
                print("\n暂无书籍，请先添加或同步")
                return

            print("\n{:<5} {:<30} {:<20} {:<10}".format(
                "ID", "书名", "番茄书籍ID", "章节数"))
            print("-" * 70)
            for book in books:
                chapter_count = db.query(Chapter).filter_by(book_id=book.id).count()
                print("{:<5} {:<30} {:<20} {:<10}".format(
                    book.id,
                    book.title[:28],
                    str(book.fanqie_book_id)[:18],
                    chapter_count
                ))
        finally:
            db.close()

    def do_sync_books(self, arg):
        """sync_books - 从番茄后台同步书籍列表"""
        if not self.current_account_id:
            print("请先选择账号: use <账号ID>")
            return

        print("正在同步书籍...")

        async def _sync():
            from browser.fanqie.scanner import FanqieBookScanner
            scanner = FanqieBookScanner()
            books = await scanner.scan_books(self.current_account_id)
            print(f"同步完成，共获取 {len(books)} 本书籍")
            return books

        self._run_async(_sync())

    def do_sync_chapters(self, arg):
        """sync_chapters <书籍ID> - 同步指定书籍的章节"""
        if not arg:
            print("用法: sync_chapters <书籍ID>")
            return

        try:
            book_id = int(arg)
        except ValueError:
            print("书籍ID必须是数字")
            return

        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                print(f"书籍 {book_id} 不存在")
                return

            print(f"正在同步书籍 '{book.title}' 的章节...")

            # 扫描本地章节
            if book.local_folder:
                scanner = ChapterScanner(book.local_folder)
                chapters = scanner.scan()
                print(f"从 {book.local_folder} 扫描到 {len(chapters)} 个章节文件")

                # 更新到数据库
                chapter_tracker.sync_chapters(book_id)
                db = get_session()
                try:
                    count = db.query(Chapter).filter_by(book_id=book_id).count()
                    print(f"数据库中该书籍共有 {count} 个章节")
                finally:
                    db.close()
            else:
                print("该书籍未设置本地文件夹")
        finally:
            db.close()

    def do_book_info(self, arg):
        """book_info <书籍ID> - 查看书籍详细信息"""
        if not arg:
            print("用法: book_info <书籍ID>")
            return

        try:
            book_id = int(arg)
        except ValueError:
            print("书籍ID必须是数字")
            return

        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                print(f"书籍 {book_id} 不存在")
                return

            chapters = db.query(Chapter).filter_by(book_id=book_id).all()
            pending = sum(1 for c in chapters if c.status == "pending")
            published = sum(1 for c in chapters if c.status == "published")
            failed = sum(1 for c in chapters if c.status == "failed")

            print(f"\n书籍信息:")
            print(f"  ID: {book.id}")
            print(f"  书名: {book.title}")
            print(f"  番茄书籍ID: {book.fanqie_book_id}")
            print(f"  本地文件夹: {book.local_folder}")
            print(f"  章节总数: {len(chapters)}")
            print(f"  待发布: {pending}")
            print(f"  已发布: {published}")
            print(f"  失败: {failed}")
        finally:
            db.close()

    # ==================== 章节管理 ====================

    def do_chapters(self, arg):
        """chapters <书籍ID> - 查看书籍的章节列表"""
        if not arg:
            print("用法: chapters <书籍ID>")
            return

        try:
            book_id = int(arg)
        except ValueError:
            print("书籍ID必须是数字")
            return

        db = get_session()
        try:
            chapters = db.query(Chapter).filter_by(book_id=book_id).order_by(Chapter.id).all()
            if not chapters:
                print("暂无章节，请先同步")
                return

            print("\n{:<5} {:<35} {:<10} {:<10}".format(
                "ID", "章节标题", "状态", "字数"))
            print("-" * 65)
            for ch in chapters:
                print("{:<5} {:<35} {:<10} {:<10}".format(
                    ch.id,
                    ch.chapter_title[:33],
                    ch.status,
                    ch.word_count or 0
                ))
        finally:
            db.close()

    def do_pending_chapters(self, arg):
        """pending_chapters <书籍ID> - 查看待发布的章节"""
        if not arg:
            print("用法: pending_chapters <书籍ID>")
            return

        try:
            book_id = int(arg)
        except ValueError:
            print("书籍ID必须是数字")
            return

        db = get_session()
        try:
            chapters = db.query(Chapter).filter_by(
                book_id=book_id, status="pending"
            ).order_by(Chapter.id).all()

            if not chapters:
                print("没有待发布的章节")
                return

            print(f"\n待发布的章节 ({len(chapters)} 个):")
            print("\n{:<5} {:<35} {:<10}".format("ID", "章节标题", "字数"))
            print("-" * 55)
            for ch in chapters:
                print("{:<5} {:<35} {:<10}".format(
                    ch.id,
                    ch.chapter_title[:33],
                    ch.word_count or 0
                ))
        finally:
            db.close()

    # ==================== 发布操作 ====================

    def do_publish(self, arg):
        """publish <书籍ID> - 添加待发布任务（会检查是否已发布，自动错开发布时间）"""
        if not arg:
            print("用法: publish <书籍ID>")
            print("\n示例:")
            print("  publish 1           # 查看书籍1的待发布章节并选择")
            print("  publish 1 1-5      # 发布书籍1的第1-5章")
            print("  publish 1 1,3,5    # 发布书籍1的第1、3、5章")
            print("  publish 1 all       # 发布书籍1所有待发布章节")
            print("\n说明:")
            print("  - 多章节发布时会自动错开发布时间(1-2分钟)")
            print("  - 任务会写入待发布列表，由定时器执行")
            return

        args = arg.split()
        try:
            book_id = int(args[0])
        except ValueError:
            print("书籍ID必须是数字")
            return

        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                print(f"书籍 {book_id} 不存在")
                return

            if not book.fanqie_book_id:
                print("该书籍未设置番茄书籍ID")
                return

            # 检查账号
            account = db.query(Account).filter_by(id=book.account_id).first()
            if not account or account.status != "active":
                print("账号不可用，请先登录")
                return

            # 获取待发布的章节
            pending_chapters = db.query(Chapter).filter_by(
                book_id=book_id, status="pending"
            ).order_by(Chapter.id).all()

            if not pending_chapters:
                print("\n没有待发布的章节")
                return

            # 解析选择参数
            selected_chapters = []
            if len(args) > 1:
                selection = args[1]
                if selection.lower() == "all":
                    selected_chapters = pending_chapters
                else:
                    # 解析范围或逗号分隔
                    selected_ids = self._parse_chapter_selection(selection, pending_chapters)
                    selected_ids.sort()
                    selected_chapters = [c for c in pending_chapters if c.id in selected_ids]
            else:
                # 交互式选择
                selected_ids = self._interactive_select_chapters(pending_chapters)
                if not selected_ids:
                    print("\n没有选择任何章节，发布取消")
                    return
                selected_chapters = [c for c in pending_chapters if c.id in selected_ids]

            if not selected_chapters:
                print("\n没有选择任何章节，发布取消")
                return

        finally:
            db.close()

        # 先检查番茄上是否已有这些章节
        print("\n正在检查番茄小说上是否已有这些章节...")
        check_result = self._run_async_check(book.fanqie_book_id, account.id, selected_chapters)

        if not check_result:
            print("检查失败，将继续添加所有选择的章节到待发列表")
            to_publish_chapters = selected_chapters
            skipped_chapters = []
        else:
            # check_result 返回的是章节对象列表
            to_publish_chapters = check_result.get('to_publish', [])
            skipped_chapters = check_result.get('skipped', [])

            if skipped_chapters:
                print(f"\n发现 {len(skipped_chapters)} 个章节已在番茄上存在，将被跳过:")
                for ch in skipped_chapters:
                    print(f"  [跳过] {ch.chapter_title}")

            if not to_publish_chapters:
                print("所有选择的章节都已在番茄上存在，无需发布")
                # 记录跳过的日志
                self._log_skipped_chapters(skipped_chapters, account.id)
                return

        # 显示发布预览
        print(f"\n{'='*70}")
        print(f"  发布预览 (共 {len(to_publish_chapters)} 个章节)")
        print(f"{'='*70}")
        print(f"{'序号':<6} {'章节ID':<8} {'章节标题':<40}")
        print("-" * 70)
        for i, ch in enumerate(to_publish_chapters, 1):
            print(f"{i:<6} {ch.id:<8} {ch.chapter_title[:38]:<40}")
        print("-" * 70)

        # 询问起始时间
        print("\n设置起始发布时间:")
        print("  +0    - 立即开始发布")
        print("  +1    - 1分钟后开始")
        print("  +5    - 5分钟后开始")
        print("  20:00 - 今天20:00开始")
        print("  2024-03-30 20:00 - 特定时间开始")

        while True:
            time_input = input("\n请输入起始时间 (直接回车默认+1): ").strip()
            if not time_input:
                time_input = "+1"

            start_time = self._parse_time(time_input)
            if start_time:
                break
            print("时间格式错误，请重新输入")

        # 计算各章节发布时间
        import random
        from datetime import timedelta

        schedule_times = []
        current_time = start_time

        print(f"\n{'='*70}")
        print(f"  发布计划")
        print(f"{'='*70}")
        print(f"{'序号':<6} {'章节ID':<8} {'章节标题':<30} {'发布时间':<25}")
        print("-" * 70)

        for i, ch in enumerate(to_publish_chapters):
            schedule_times.append((ch, current_time))
            time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{i+1:<6} {ch.id:<8} {ch.chapter_title[:28]:<30} {time_str:<25}")

            if i < len(to_publish_chapters) - 1:
                # 每个章节之间延迟
                delay = random.randint(PUBLISH_DELAY_MIN, PUBLISH_DELAY_MAX)
                current_time = current_time + timedelta(seconds=delay)

        print("-" * 70)

        # 确认发布
        confirm = input("\n确认添加到待发布列表? (y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return

        # 添加到待发布列表
        db = get_session()
        try:
            added_count = 0
            for ch, scheduled_time in schedule_times:
                # 检查是否已有待发任务
                existing = db.query(PendingTask).filter_by(
                    chapter_id=ch.id, status="pending"
                ).first()

                if existing:
                    print(f"  章节 '{ch.chapter_title}' 已有待发任务，跳过")
                    continue

                task = PendingTask(
                    chapter_id=ch.id,
                    scheduled_time=scheduled_time,
                    status="pending"
                )
                db.add(task)
                added_count += 1

            db.commit()
            print(f"\n已添加 {added_count} 个章节到待发布列表")
            print("使用 'tasks' 命令可查看待发布任务")
            print("定时器会自动按计划执行发布")

        except Exception as e:
            print(f"添加失败: {e}")
            db.rollback()
        finally:
            db.close()

        # 记录跳过的日志
        if skipped_chapters:
            self._log_skipped_chapters(skipped_chapters, account.id)

    def _log_skipped_chapters(self, chapters: list, account_id: int):
        """记录被跳过的章节日志"""
        try:
            db = get_session()
            try:
                for ch in chapters:
                    # 检查是否已有跳过记录
                    existing = db.query(PublishLog).filter_by(
                        chapter_id=ch.id,
                        action='skip_existed'
                    ).first()

                    if not existing:
                        log = PublishLog(
                            chapter_id=ch.id,
                            account_id=account_id,
                            action='skip_existed',
                            status='skipped',
                            message='章节在番茄小说上已存在，自动跳过',
                            duration_ms=0
                        )
                        db.add(log)

                db.commit()
                logger.info(f"已记录 {len(chapters)} 个跳过日志")
            except Exception as e:
                logger.error(f"记录跳过日志失败: {e}")
                db.rollback()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"记录跳过日志失败: {e}")

    def _run_async_check(self, fanqie_book_id: str, account_id: int, chapters: list) -> Optional[dict]:
        """异步检查章节是否存在"""
        async def _check():
            from browser.manager import browser_manager
            from browser.fanqie.chapter_checker import ChapterChecker

            # 获取账号锁
            account_lock = await browser_manager.async_get_account_lock(account_id)
            async with account_lock:
                context = await browser_manager._async_create_context_from_session(account_id)
                if not context:
                    logger.error(f"无法获取账号 {account_id} 的浏览器Context")
                    return None

                page = await context.new_page()
                checker = ChapterChecker(page)

                try:
                    # 获取番茄上已发布的章节
                    published = await checker.get_published_chapters(fanqie_book_id)
                    logger.info(f"番茄上已有 {len(published)} 个章节")

                    to_publish = []
                    skipped = []

                    for ch in chapters:
                        title = checker._clean_title(ch.chapter_title)

                        # 检查是否已存在
                        is_exists = False
                        for pub_title in published:
                            if _titles_match(title, pub_title):
                                is_exists = True
                                break

                        if is_exists:
                            skipped.append(ch)
                        else:
                            to_publish.append(ch)

                    return {
                        'published': published,
                        'to_publish': to_publish,
                        'skipped': skipped
                    }

                finally:
                    await page.close()
                    await context.close()

        try:
            # 使用 browser_manager 的线程安全异步执行
            return browser_manager._run_async(_check())
        except Exception as e:
            logger.error(f"检查章节失败: {e}")
            return None

    def _parse_chapter_selection(self, selection: str, chapters: list) -> list:
        """解析章节选择字符串"""
        chapter_ids = []
        chapter_map = {c.id: c for c in chapters}

        # 支持格式: "1-5", "1,3,5", "1-3,5,7-9"
        parts = selection.split(",")

        for part in parts:
            part = part.strip()
            if "-" in part:
                # 范围选择
                try:
                    start, end = part.split("-")
                    start_id = int(start.strip())
                    end_id = int(end.strip())

                    # 找到范围内的章节
                    for ch in chapters:
                        if start_id <= ch.id <= end_id:
                            chapter_ids.append(ch.id)
                except ValueError:
                    print(f"  警告: 无法解析范围 '{part}'")
            else:
                # 单个选择
                try:
                    ch_id = int(part.strip())
                    if ch_id in chapter_map:
                        chapter_ids.append(ch_id)
                    else:
                        print(f"  警告: 章节 {ch_id} 不在待发布列表中")
                except ValueError:
                    print(f"  警告: 无法解析章节ID '{part}'")

        return chapter_ids

    def _interactive_select_chapters(self, chapters: list) -> list:
        """交互式选择章节"""
        print(f"\n{'='*60}")
        print(f"  待发布章节列表 (共 {len(chapters)} 个)")
        print(f"{'='*60}")
        print(f"{'序号':<6} {'ID':<6} {'章节标题':<40} {'字数':<8}")
        print(f"{'-'*60}")

        for i, ch in enumerate(chapters, 1):
            print(f"{i:<6} {ch.id:<6} {ch.chapter_title[:38]:<40} {ch.word_count or 0:<8}")

        print(f"{'-'*60}")
        print()
        print("选择方式:")
        print("  1-5      - 发布第1到5章")
        print("  1,3,5    - 发布第1、3、5章")
        print("  1-3,5,7  - 混合选择")
        print("  all      - 发布全部")
        print("  q        - 取消")
        print()

        while True:
            choice = input("请输入选择: ").strip().lower()

            if choice == "q":
                return []

            if not choice:
                continue

            # 尝试解析
            chapter_ids = self._parse_chapter_selection(choice, chapters)
            if chapter_ids:
                return chapter_ids

            print("输入无效，请重新输入 (或输入 q 取消)")

    def do_publish_single(self, arg):
        """publish_single <章节ID> - 发布单个章节"""
        if not arg:
            print("用法: publish_single <章节ID>")
            return

        try:
            chapter_id = int(arg)
        except ValueError:
            print("章节ID必须是数字")
            return

        db = get_session()
        try:
            chapter = db.query(Chapter).filter_by(id=chapter_id).first()
            if not chapter:
                print(f"章节 {chapter_id} 不存在")
                return

            book = db.query(Book).filter_by(id=chapter.book_id).first()
            if not book:
                print("章节所属书籍不存在")
                return

            if not book.fanqie_book_id:
                print("书籍未设置番茄书籍ID")
                return

            account = db.query(Account).filter_by(id=book.account_id).first()
            if not account or account.status != "active":
                print("账号不可用，请先登录")
                return

            print(f"正在发布章节 '{chapter.chapter_title}' ...")
        finally:
            db.close()

        # 执行发布
        async def _publish():
            from web.routes.publish import _async_execute_publish
            await _async_execute_publish(
                book_id=book.id,
                account_id=account.id,
                fanqie_book_id=book.fanqie_book_id,
                chapter_ids=[chapter_id]
            )

        self._run_async(_publish())

    # ==================== 待发任务 ====================

    def do_tasks(self, arg):
        """tasks - 查看待发布任务列表"""
        db = get_session()
        try:
            tasks = db.query(PendingTask).filter_by(status="pending").order_by(PendingTask.scheduled_time).all()
            if not tasks:
                print("\n暂无待发布任务")
                return

            print("\n" + "=" * 100)
            print(f"  待发布任务列表 (共 {len(tasks)} 个)")
            print("=" * 100)
            print(f"{'ID':<4} {'账号':<10} {'小说名':<20} {'章节标题':<28} {'创建时间':<20} {'发布时间':<20}")
            print("-" * 100)

            for task in tasks:
                account_name = task.chapter.book.account.name if task.chapter and task.chapter.book and task.chapter.book.account else "未知"
                book_name = task.chapter.book.book_name[:18] if task.chapter and task.chapter.book else "未知"
                chapter_title = task.chapter.chapter_title[:26] if task.chapter else "未知"
                created_at = str(task.created_at)[:19] if task.created_at else ""
                scheduled = str(task.scheduled_time)[:19] if task.scheduled_time else ""

                print(f"{task.id:<4} {account_name:<10} {book_name:<20} {chapter_title:<28} {created_at:<20} {scheduled:<20}")

            print("-" * 100)
            print("\n可用命令:")
            print("  add_task <章节ID> <发布时间>  - 添加待发任务")
            print("  del_task <任务ID>            - 删除任务")
            print("  edit_task <任务ID> <新时间>   - 修改发布时间")
            print("  run_tasks                   - 执行所有待发任务")

        finally:
            db.close()

    def do_add_task(self, arg):
        """add_task <章节ID> <发布时间> - 添加待发布任务"""
        args = arg.split(maxsplit=1)
        if len(args) < 2:
            print("用法: add_task <章节ID> <发布时间>")
            print("\n时间格式示例:")
            print("  2024-03-29 20:00    - 特定时间")
            print("  20:00              - 今天20:00")
            print("  +30                - 30分钟后")
            print("  +1h                - 1小时后")
            print("  +1d                - 1天后")
            return

        try:
            chapter_id = int(args[0])
            time_str = args[1]
        except ValueError:
            print("章节ID必须是数字")
            return

        # 解析时间
        scheduled_time = self._parse_time(time_str)
        if not scheduled_time:
            return

        db = get_session()
        try:
            chapter = db.query(Chapter).filter_by(id=chapter_id).first()
            if not chapter:
                print(f"章节 {chapter_id} 不存在")
                return

            # 检查是否已有待发任务
            existing = db.query(PendingTask).filter_by(
                chapter_id=chapter_id, status="pending"
            ).first()
            if existing:
                print(f"该章节已有待发任务 (ID: {existing.id}, 发布时间: {existing.scheduled_time})")
                return

            # 创建任务
            task = PendingTask(
                chapter_id=chapter_id,
                scheduled_time=scheduled_time,
                status="pending"
            )
            db.add(task)
            db.commit()

            book_name = chapter.book.book_name if chapter.book else "未知"
            print(f"\n已添加待发任务:")
            print(f"  章节: {chapter.chapter_title}")
            print(f"  小说: {book_name}")
            print(f"  发布时间: {scheduled_time}")

        except Exception as e:
            print(f"添加失败: {e}")
            db.rollback()
        finally:
            db.close()

    def do_del_task(self, arg):
        """del_task <任务ID> - 删除待发布任务"""
        if not arg:
            print("用法: del_task <任务ID>")
            return

        try:
            task_id = int(arg)
        except ValueError:
            print("任务ID必须是数字")
            return

        db = get_session()
        try:
            task = db.query(PendingTask).filter_by(id=task_id).first()
            if not task:
                print(f"任务 {task_id} 不存在")
                return

            chapter_title = task.chapter.chapter_title if task.chapter else "未知"
            print(f"\n确认删除任务 {task_id}?")
            print(f"  章节: {chapter_title}")
            print(f"  发布时间: {task.scheduled_time}")

            confirm = input("\n输入 y 确认删除: ").strip().lower()
            if confirm != 'y':
                print("已取消")
                return

            db.delete(task)
            db.commit()
            print("已删除")

        except Exception as e:
            print(f"删除失败: {e}")
            db.rollback()
        finally:
            db.close()

    def do_edit_task(self, arg):
        """edit_task <任务ID> <新发布时间> - 修改发布时间"""
        args = arg.split(maxsplit=1)
        if len(args) < 2:
            print("用法: edit_task <任务ID> <新发布时间>")
            print("\n时间格式示例:")
            print("  2024-03-29 20:00    - 特定时间")
            print("  20:00              - 今天20:00")
            print("  +30                - 30分钟后")
            print("  +1h                - 1小时后")
            print("  +1d                - 1天后")
            return

        try:
            task_id = int(args[0])
            time_str = args[1]
        except ValueError:
            print("任务ID必须是数字")
            return

        # 解析时间
        new_time = self._parse_time(time_str)
        if not new_time:
            return

        db = get_session()
        try:
            task = db.query(PendingTask).filter_by(id=task_id).first()
            if not task:
                print(f"任务 {task_id} 不存在")
                return

            old_time = task.scheduled_time
            task.scheduled_time = new_time
            db.commit()

            chapter_title = task.chapter.chapter_title if task.chapter else "未知"
            print(f"\n已修改任务 {task_id} 的发布时间:")
            print(f"  章节: {chapter_title}")
            print(f"  原时间: {old_time}")
            print(f"  新时间: {new_time}")

        except Exception as e:
            print(f"修改失败: {e}")
            db.rollback()
        finally:
            db.close()

    def do_run_tasks(self, arg):
        """run_tasks - 执行已到时的待发任务"""
        from datetime import datetime

        db = get_session()
        try:
            now = datetime.now()
            tasks = db.query(PendingTask).filter_by(status="pending").order_by(PendingTask.scheduled_time).all()

            due_tasks = [t for t in tasks if t.scheduled_time <= now]
            future_tasks = [t for t in tasks if t.scheduled_time > now]

            if not tasks:
                print("\n暂无待发布任务")
                return

            print(f"\n待发布任务: {len(tasks)} 个")
            print(f"  待执行: {len(due_tasks)} 个")
            print(f"  等待中: {len(future_tasks)} 个")

            if due_tasks:
                print(f"\n以下 {len(due_tasks)} 个任务已到时，将立即执行:")
                for task in due_tasks:
                    chapter_title = task.chapter.chapter_title if task.chapter else "未知"
                    print(f"  [{task.id}] {chapter_title}")

                confirm = input("\n确认执行? (y/n): ").strip().lower()
                if confirm != 'y':
                    print("已取消")
                    return

                # 执行任务
                self._execute_pending_tasks(due_tasks)
            else:
                print("\n没有已到时的任务")
                if future_tasks:
                    next_task = future_tasks[0]
                    chapter_title = next_task.chapter.chapter_title if next_task.chapter else "未知"
                    print(f"下一个任务: {chapter_title} @ {next_task.scheduled_time}")

        finally:
            db.close()

    def _parse_time(self, time_str: str):
        """解析时间字符串"""
        from datetime import datetime, timedelta

        time_str = time_str.strip()

        # +30 格式（多少分钟后）
        if time_str.startswith('+'):
            match = re.match(r'\+(\d+)([hmd])?', time_str)
            if match:
                value = int(match.group(1))
                unit = match.group(2) or 'm'  # 默认分钟

                now = datetime.now()
                if unit == 'h':
                    return now + timedelta(hours=value)
                elif unit == 'd':
                    return now + timedelta(days=value)
                else:
                    return now + timedelta(minutes=value)

        # HH:MM 格式（今天几点）
        match = re.match(r'(\d{1,2}):(\d{2})', time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            now = datetime.now()
            result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # 如果时间已过，算明天
            if result <= now:
                result += timedelta(days=1)
            return result

        # 完整日期时间格式
        formats = [
            '%Y-%m-%d %H:%M',
            '%Y/%m/%d %H:%M',
            '%Y-%m-%d %H:%M:%S',
            '%Y/%m/%d %H:%M:%S',
        ]

        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        print(f"无法解析时间: {time_str}")
        print("支持的格式: YYYY-MM-DD HH:MM, HH:MM, +30, +1h, +1d")
        return None

    def _execute_pending_tasks(self, tasks: list):
        """执行待发布任务"""
        async def _run():
            from web.routes.publish import _async_execute_publish

            total = len(tasks)
            for i, task in enumerate(tasks):
                db = get_session()
                try:
                    # 标记为执行中
                    task.status = "publishing"
                    db.commit()

                    chapter = task.chapter
                    if not chapter or not chapter.book:
                        task.status = "cancelled"
                        task.notes = "章节或书籍不存在"
                        db.commit()
                        continue

                    book = chapter.book
                    account = book.account

                    if not account or account.status != "active":
                        task.status = "cancelled"
                        task.notes = "账号不可用"
                        db.commit()
                        continue

                    if not book.fanqie_book_id:
                        task.status = "cancelled"
                        task.notes = "书籍未设置番茄ID"
                        db.commit()
                        continue

                    print(f"\n[{i+1}/{total}] 正在发布: {chapter.chapter_title}...")

                    await _async_execute_publish(
                        book_id=book.id,
                        account_id=account.id,
                        fanqie_book_id=book.fanqie_book_id,
                        chapter_ids=[chapter.id]
                    )

                    # 标记为已发布
                    task.status = "published"
                    db.commit()
                    print(f"  发布完成")

                    # 发布间隔
                    if i < total - 1:
                        print(f"\n等待 {PUBLISH_DELAY_BETWEEN_CHAPTERS} 秒...")
                        await asyncio.sleep(PUBLISH_DELAY_BETWEEN_CHAPTERS)

                except Exception as e:
                    logger.error(f"执行任务失败: {e}")
                    task.status = "cancelled"
                    task.notes = str(e)
                    db.commit()
                finally:
                    db.close()

            print(f"\n任务执行完成！共 {total} 个")

        self._run_async(_run())

    # ==================== 定时任务 ====================

    def do_schedules(self, arg):
        """schedules - 查看所有定时任务"""
        db = get_session()
        try:
            schedules = db.query(Schedule).all()
            if not schedules:
                print("\n暂无定时任务")
                return

            print("\n{:<5} {:<30} {:<20} {:<10}".format(
                "ID", "书籍", "执行时间", "状态"))
            print("-" * 70)
            for sch in schedules:
                book = db.query(Book).filter_by(id=sch.book_id).first()
                print("{:<5} {:<30} {:<20} {:<10}".format(
                    sch.id,
                    book.title[:28] if book else "未知",
                    str(sch.cron_expression)[:18],
                    sch.status
                ))
        finally:
            db.close()

    def do_add_schedule(self, arg):
        """add_schedule <书籍ID> <cron表达式> - 添加定时发布任务"""
        # 例如: add_schedule 1 0 2 * * *  (每天凌晨2点)
        args = arg.split()
        if len(args) < 2:
            print("用法: add_schedule <书籍ID> <cron表达式>")
            print("  例如: add_schedule 1 0 2 * * *  (每天凌晨2点)")
            return

        try:
            book_id = int(args[0])
            cron_expr = " ".join(args[1:])
        except ValueError:
            print("书籍ID必须是数字")
            return

        print(f"定时任务功能开发中...")
        # TODO: 实现定时任务添加

    # ==================== 日志 ====================

    def do_logs(self, arg):
        """logs [数量=20] - 查看发布日志"""
        try:
            limit = int(arg) if arg else 20
        except ValueError:
            limit = 20

        db = get_session()
        try:
            logs = db.query(PublishLog).order_by(
                PublishLog.created_at.desc()
            ).limit(limit).all()

            if not logs:
                print("\n暂无日志")
                return

            print("\n{:<5} {:<30} {:<10} {:<20}".format(
                "ID", "章节", "状态", "时间"))
            print("-" * 70)
            for log in logs:
                chapter = db.query(Chapter).filter_by(id=log.chapter_id).first()
                title = chapter.chapter_title[:28] if chapter else f"章节{log.chapter_id}"
                print("{:<5} {:<30} {:<10} {:<20}".format(
                    log.id,
                    title,
                    log.status,
                    str(log.created_at)[:19]
                ))
        finally:
            db.close()

    def do_log_detail(self, arg):
        """log_detail <日志ID> - 查看日志详情"""
        if not arg:
            print("用法: log_detail <日志ID>")
            return

        try:
            log_id = int(arg)
        except ValueError:
            print("日志ID必须是数字")
            return

        db = get_session()
        try:
            log = db.query(PublishLog).filter_by(id=log_id).first()
            if not log:
                print(f"日志 {log_id} 不存在")
                return

            chapter = db.query(Chapter).filter_by(id=log.chapter_id).first()
            account = db.query(Account).filter_by(id=log.account_id).first()

            print(f"\n日志详情:")
            print(f"  ID: {log.id}")
            print(f"  章节: {chapter.chapter_title if chapter else '未知'}")
            print(f"  账号: {account.name if account else '未知'}")
            print(f"  操作: {log.action}")
            print(f"  状态: {log.status}")
            print(f"  消息: {log.message}")
            print(f"  耗时: {log.duration_ms}ms")
            print(f"  时间: {log.created_at}")
        finally:
            db.close()

    # ==================== 工具 ====================

    def do_check_session(self, arg):
        """check_session - 检查当前账号的Session状态"""
        if not self.current_account_id:
            print("请先选择账号: use <账号ID>")
            return

        print("正在检查Session...")

        async def _check():
            from browser.fanqie.login import check_session_valid
            valid = await check_session_valid(self.current_account_id)
            if valid:
                print("Session有效!")
            else:
                print("Session已过期，需要重新登录")

        self._run_async(_check())

    def do_clear_chapters(self, arg):
        """clear_chapters <书籍ID> - 清除书籍章节状态（重新发布）"""
        if not arg:
            print("用法: clear_chapters <书籍ID>")
            return

        try:
            book_id = int(arg)
        except ValueError:
            print("书籍ID必须是数字")
            return

        db = get_session()
        try:
            count = db.query(Chapter).filter_by(book_id=book_id).update({
                Chapter.status: "pending",
                Chapter.published_at: None,
                Chapter.fanqie_chapter_id: None,
                Chapter.error_message: None
            })
            db.commit()
            print(f"已重置 {count} 个章节状态为待发布")
        finally:
            db.close()

    # ==================== 系统 ====================

    def do_status(self, arg):
        """status - 查看系统状态"""
        db = get_session()
        try:
            account_count = db.query(Account).count()
            book_count = db.query(Book).count()
            chapter_count = db.query(Chapter).count()
            pending_count = db.query(Chapter).filter_by(status="pending").count()
            schedule_count = db.query(Schedule).count()

            print(f"\n系统状态:")
            print(f"  账号数: {account_count}")
            print(f"  书籍数: {book_count}")
            print(f"  章节数: {chapter_count}")
            print(f"  待发布: {pending_count}")
            print(f"  定时任务: {schedule_count}")
            print(f"  当前账号: {self.current_account_id or '未设置'}")
        finally:
            db.close()

    def do_exit(self, arg):
        """exit - 退出程序"""
        print("正在关闭系统...")
        shutdown_scheduler()
        browser_manager.stop()
        print("再见!")
        return True

    def do_quit(self, arg):
        """quit - 退出程序"""
        return self.do_exit(arg)

    def do_EOF(self, arg):
        """Ctrl+D 退出"""
        print()
        return self.do_exit(arg)

    # ==================== 辅助方法 ====================

    def _run_async(self, coro):
        """在新的事件循环中运行协程"""
        try:
            asyncio.run(coro)
        except Exception as e:
            print(f"执行出错: {e}")

    def emptyline(self):
        """空行不重复上一命令"""
        pass

    def default(self, line):
        """未知命令"""
        print(f"未知命令: {line}")
        print("输入 help 查看可用命令")


def _titles_match(title1: str, title2: str) -> bool:
    """判断两个章节标题是否匹配"""
    if not title1 or not title2:
        return False

    # 精确匹配
    if title1 == title2:
        return True

    # 去除数字后的匹配（处理序号可能不同的情况）
    t1_no_num = re.sub(r'[\d]+', '', title1)
    t2_no_num = re.sub(r'[\d]+', '', title2)

    # 简化比较：去除空格和标点
    t1_simple = re.sub(r'[\s\.\-\_～\：\:\、\，]', '', t1_no_num)
    t2_simple = re.sub(r'[\s\.\-\_～\：\:\、\，]', '', t2_no_num)

    if t1_simple == t2_simple:
        return True

    # 一个包含另一个（允许轻微差异）
    if len(t1_simple) > 3 and len(t2_simple) > 3:
        if t1_simple in t2_simple or t2_simple in t1_simple:
            return True

    return False


def init_system():
    """初始化系统"""
    logger.info("初始化数据库...")
    init_db()
    logger.info("启动调度器...")
    init_scheduler()
    add_session_check_job()
    add_cleanup_job()
    recover_missed_schedules()
    logger.info("系统就绪!")


def main():
    """主入口"""
    print("=" * 50)
    print("番茄小说自动发布器 v1.0")
    print("=" * 50)

    # 初始化
    init_system()

    # 启动待发布任务调度器
    from scheduler.task_scheduler import task_scheduler
    task_scheduler.start()

    # 启动CLI
    cli = FanqieCLI()

    # 信号处理
    def signal_handler(sig, frame):
        print("\n\n正在关闭...")
        task_scheduler.stop()
        shutdown_scheduler()
        browser_manager.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        cli.run()
    except KeyboardInterrupt:
        print("\n再见!")


if __name__ == "__main__":
    main()
