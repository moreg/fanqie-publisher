"""
异步浏览器管理器 - 使用Playwright异步API
解决sync_playwright在后台线程中的greenlet兼容性问题
"""

import asyncio
import json
import threading
import queue
from pathlib import Path
from typing import Optional, Any

from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext

from config import SESSIONS_DIR, BROWSER_HEADLESS, PAGE_LOAD_TIMEOUT, ASYNC_BROWSER_TASK_TIMEOUT
from utils.logger import logger


class AsyncBrowserManager:
    """
    异步浏览器管理器 - 所有Playwright操作在独立事件循环线程中执行
    Flask主线程通过线程安全的队列提交任务并获取结果
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._contexts: dict[int, BrowserContext] = {}
        self._contexts_lock = threading.Lock()
        # 使用线程安全的普通锁来保护账号锁的创建
        self._account_locks_protector = threading.Lock()
        # 账号锁会在事件循环线程中按需创建
        self._account_locks: dict[int, asyncio.Lock] = {}
        self._global_lock_protector = threading.Lock()
        self._global_lock: Optional[asyncio.Lock] = None

        # 独立线程运行事件循环
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._task_queue: queue.Queue = queue.Queue()
        self._result_queues: dict[int, queue.Queue] = {}
        self._task_counter = 0
        self._task_lock = threading.Lock()

    def _ensure_started(self):
        """确保事件循环线程已启动"""
        if self._thread is None or not self._thread.is_alive():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="PlaywrightEventLoop")
            self._thread.start()
            logger.info("Playwright异步事件循环已启动")

    def _run_loop(self):
        """事件循环线程（阻塞运行）"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro) -> Any:
        """将协程提交到事件循环并返回结果"""
        self._ensure_started()

        with self._task_lock:
            task_id = self._task_counter
            self._task_counter += 1
            result_queue = queue.Queue()
            self._result_queues[task_id] = result_queue

        async def wrapper():
            try:
                logger.info(f"[Task {task_id}] 开始执行异步任务")
                result = await coro
                logger.info(f"[Task {task_id}] 异步任务完成")
                result_queue.put(("ok", result))
            except Exception as e:
                logger.error(f"[Task {task_id}] 异步任务失败: {e}")
                result_queue.put(("err", e))

        future = asyncio.run_coroutine_threadsafe(wrapper(), self._loop)
        logger.info(f"[Task {task_id}] 已提交到事件循环")

        # 等待结果（默认 1 小时，可通过 ASYNC_BROWSER_TASK_TIMEOUT 配置）
        try:
            status, value = result_queue.get(timeout=ASYNC_BROWSER_TASK_TIMEOUT)
        except queue.Empty:
            with self._task_lock:
                del self._result_queues[task_id]
            msg = (
                f"异步任务等待超时（{ASYNC_BROWSER_TASK_TIMEOUT} 秒）。"
                "可适当增大环境变量 ASYNC_BROWSER_TASK_TIMEOUT。"
            )
            logger.error(f"[Task {task_id}] {msg}")
            raise TimeoutError(msg) from None
        with self._task_lock:
            del self._result_queues[task_id]

        if status == "err":
            raise value
        return value

    def start(self):
        """启动浏览器"""
        async def _start():
            if self._browser is not None:
                return
            logger.info("正在启动Playwright浏览器...")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=BROWSER_HEADLESS,
                args=["--disable-blink-features=AutomationControlled"]
            )
            logger.info("浏览器已启动")

        self._run_async(_start())

    def stop(self):
        """关闭浏览器"""
        async def _stop():
            for account_id in list(self._contexts.keys()):
                try:
                    await self._async_close_context(account_id)
                except Exception:
                    pass
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            logger.info("浏览器已关闭")

        try:
            self._run_async(_stop())
        except Exception as e:
            logger.error(f"关闭浏览器出错: {e}")

    def get_account_lock(self, account_id: int):
        """获取账号级别的锁（在事件循环线程中创建）"""
        async def _get():
            global_lock = await self._async_get_global_lock()
            async with global_lock:
                if account_id not in self._account_locks:
                    self._account_locks[account_id] = asyncio.Lock()
                return self._account_locks[account_id]

        return self._run_async(_get())

    async def _async_get_global_lock(self) -> asyncio.Lock:
        """获取全局锁（线程安全创建）"""
        with self._global_lock_protector:
            if self._global_lock is None:
                self._global_lock = asyncio.Lock()
            return self._global_lock

    async def async_get_account_lock(self, account_id: int):
        """异步获取账号级别的锁"""
        global_lock = await self._async_get_global_lock()
        async with global_lock:
            if account_id not in self._account_locks:
                self._account_locks[account_id] = asyncio.Lock()
            return self._account_locks[account_id]

    def get_session_path(self, account_id: int) -> Path:
        """获取Session文件路径"""
        return self._get_session_path(account_id)

    async def _async_ensure_browser(self):
        """确保浏览器已启动（异步版本）"""
        if self._browser is not None:
            return True
        logger.info("正在启动Playwright浏览器...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=BROWSER_HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized"
            ]
        )
        logger.info("浏览器已启动")
        return True

    def _get_session_path(self, account_id: int) -> Path:
        return SESSIONS_DIR / f"{account_id}_state.json"

    async def _async_create_context_from_session(self, account_id: int) -> Optional[BrowserContext]:
        """从已保存的Session或Cookie创建Context（异步版本）"""
        # 先确保浏览器已启动
        await self._async_ensure_browser()

        await self._async_close_context(account_id)

        # 优先使用数据库中的 cookies
        cookies = await self._async_get_account_cookies(account_id)
        if cookies:
            try:
                context = await self._browser.new_context(
                    viewport=None,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                # 添加 cookies
                await context.add_cookies(cookies)
                context.set_default_timeout(PAGE_LOAD_TIMEOUT)
                with self._contexts_lock:
                    self._contexts[account_id] = context
                logger.info(f"已从Cookie创建账号 {account_id} 的浏览器Context")
                return context
            except Exception as e:
                logger.error(f"从Cookie创建Context失败 (账号 {account_id}): {e}")
                return None

        # 备用：使用 session 文件
        session_path = self._get_session_path(account_id)
        if not session_path.exists():
            logger.warning(f"账号 {account_id} 的Session文件和Cookie都不存在")
            return None

        try:
            context = await self._browser.new_context(
                storage_state=str(session_path),
                viewport=None,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            context.set_default_timeout(PAGE_LOAD_TIMEOUT)
            with self._contexts_lock:
                self._contexts[account_id] = context
            logger.info(f"已从Session恢复账号 {account_id} 的浏览器Context")
            return context
        except Exception as e:
            logger.error(f"从Session创建Context失败 (账号 {account_id}): {e}")
            return None

    def create_context_from_session(self, account_id: int) -> Optional[BrowserContext]:
        """从已保存的Session创建Context"""
        async def _create():
            return await self._async_create_context_from_session(account_id)

        return self._run_async(_create())

    async def _async_get_account_cookies(self, account_id: int) -> Optional[list]:
        """从数据库获取账号的cookies，支持字符串格式和JSON格式"""
        try:
            from database.connection import get_session
            from database.models import Account

            db = get_session()
            try:
                account = db.query(Account).filter_by(id=account_id).first()
                if account and account.cookies:
                    cookies_str = account.cookies.strip()

                    # 尝试解析为JSON格式（数组）
                    if cookies_str.startswith('['):
                        cookies = json.loads(cookies_str)
                        if cookies and len(cookies) > 0:
                            logger.info(f"从数据库加载账号 {account_id} 的 {len(cookies)} 个 cookies (JSON格式)")
                            return cookies

                    # 解析字符串格式的 cookies
                    # 格式: name=value; name=value; ...
                    cookies_list = []
                    for part in cookies_str.split(';'):
                        part = part.strip()
                        if '=' in part:
                            name, value = part.split('=', 1)
                            cookies_list.append({
                                "name": name.strip(),
                                "value": value.strip(),
                                "domain": ".fanqienovel.com",
                                "path": "/"
                            })

                    if cookies_list:
                        logger.info(f"从数据库加载账号 {account_id} 的 {len(cookies_list)} 个 cookies (字符串格式)")
                        return cookies_list
            finally:
                db.close()
        except Exception as e:
            logger.error(f"获取账号 cookies 失败 (账号 {account_id}): {e}")
        return None

    async def _async_create_login_context(self, account_id: int) -> tuple[BrowserContext, Browser, Playwright]:
        """创建登录用Context（独立浏览器）"""
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized"
            ]
        )
        context = await browser.new_context(
            viewport=None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        context.set_default_timeout(PAGE_LOAD_TIMEOUT)  # 这不是async方法
        context._login_pw = pw
        context._login_browser = browser
        return context, browser, pw

    async def _async_save_session(self, account_id: int, context: BrowserContext):
        """保存Session状态"""
        session_path = self._get_session_path(account_id)
        await context.storage_state(path=str(session_path))
        logger.info(f"已保存账号 {account_id} 的Session")

    async def _async_close_context(self, account_id: int):
        """关闭Context"""
        with self._contexts_lock:
            context = self._contexts.pop(account_id, None)
        if context:
            try:
                await context.close()
            except Exception:
                pass
            logger.info(f"已关闭账号 {account_id} 的浏览器Context")

    def close_context(self, account_id: int):
        async def _close():
            await self._async_close_context(account_id)

        try:
            self._run_async(_close())
        except Exception as e:
            logger.error(f"关闭账号 {account_id} 的Context失败: {e}")

    def save_session(self, account_id: int, context: BrowserContext):
        try:
            self._run_async(self._async_save_session(account_id, context))
        except Exception as e:
            logger.error(f"保存Session失败: {e}")

    def close_login_context(self, context: BrowserContext):
        """关闭登录Context"""
        async def _close():
            try:
                browser = getattr(context, "_login_browser", None)
                pw = getattr(context, "_login_pw", None)
                await context.close()
                if browser:
                    await browser.close()
                if pw:
                    await pw.stop()
            except Exception:
                pass

        try:
            self._run_async(_close())
        except Exception:
            pass

    def get_context(self, account_id: int) -> Optional[BrowserContext]:
        with self._contexts_lock:
            return self._contexts.get(account_id)

    def has_session(self, account_id: int) -> bool:
        return self._get_session_path(account_id).exists()

    def delete_session(self, account_id: int):
        session_path = self._get_session_path(account_id)
        if session_path.exists():
            session_path.unlink()
            logger.info(f"已删除账号 {account_id} 的Session文件")


# 全局单例
browser_manager = AsyncBrowserManager()
