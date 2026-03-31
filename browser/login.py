"""
登录处理器 - 使用异步Playwright API
在后台线程中运行独立的事件循环
"""

import asyncio
import threading
from datetime import datetime

from browser.manager import browser_manager
from database.connection import safe_session
from database.models import Account
from config import FANQIE_LOGIN_URL, FANQIE_BOOK_MANAGE_URL
from utils.logger import logger


class LoginHandler:
    """处理番茄小说账号登录"""

    def __init__(self):
        self.manager = browser_manager

    def start_login(self, account_id: int, on_done: callable = None) -> dict:
        """
        开始登录流程：在后台线程中运行独立事件循环，打开有头浏览器让用户手动登录
        登录完成后调用 on_done(success: bool) 回调
        """
        logger.info(f"开始账号 {account_id} 的登录流程")
        ready_event = threading.Event()

        def run_login_loop():
            """在独立线程中运行事件循环"""
            async def _login():
                context, browser, pw = await self.manager._async_create_login_context(account_id)
                page = await context.new_page()

                try:
                    await page.goto(FANQIE_LOGIN_URL, wait_until="domcontentloaded")
                    logger.info("已打开登录页面，等待用户手动完成登录...")

                    ready_event.set()

                    max_wait = 300
                    interval = 2
                    elapsed = 0

                    while elapsed < max_wait:
                        await asyncio.sleep(interval)
                        elapsed += interval

                        try:
                            current_url = page.url
                            if "login" in current_url.lower():
                                continue
                            if "writer" in current_url and ("book-manage" in current_url or "home" in current_url):
                                await page.goto(FANQIE_BOOK_MANAGE_URL, wait_until="domcontentloaded")
                                await asyncio.sleep(2)
                                if "login" not in page.url.lower():
                                    await self.manager._async_save_session(account_id, context)
                                    logger.info(f"账号 {account_id} 登录成功!")
                                    if on_done:
                                        on_done(True)
                                    return
                        except Exception:
                            pass

                        try:
                            _ = page.url
                        except Exception:
                            logger.warning("登录窗口被关闭")
                            if on_done:
                                on_done(False)
                            return

                    logger.warning("登录等待超时")
                    if on_done:
                        on_done(False)

                except asyncio.TimeoutError:
                    logger.error("登录超时")
                    if on_done:
                        on_done(False)
                except (OSError, IOError) as e:
                    logger.error(f"登录过程发生IO错误: {e}")
                    if on_done:
                        on_done(False)
                except Exception as e:
                    logger.error(f"登录过程出错: {e}")
                    if on_done:
                        on_done(False)
                finally:
                    try:
                        await context.close()
                        await browser.close()
                        await pw.stop()
                    except Exception:
                        pass

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_login())
            finally:
                loop.close()

        thread = threading.Thread(target=run_login_loop, daemon=True, name=f"LoginThread-{account_id}")
        thread.start()

        ready_event.wait(timeout=10)

        return {"status": "waiting", "message": "登录窗口已打开，请在浏览器中完成登录"}

    def check_session(self, account_id: int) -> bool:
        """检查账号Session是否有效"""
        if not self.manager.has_session(account_id):
            return False

        async def _check():
            context = await self.manager._async_create_context_from_session(account_id)
            if context is None:
                return False

            page = await context.new_page()
            try:
                await page.goto(FANQIE_BOOK_MANAGE_URL, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
                current_url = page.url

                if "login" in current_url.lower() or current_url.rstrip("/").split("/")[-1] == "writer":
                    logger.warning(f"账号 {account_id} 的Session已过期")
                    return False

                logger.info(f"账号 {account_id} 的Session有效")
                return True
            except asyncio.TimeoutError:
                logger.error(f"检查Session超时 (账号 {account_id})")
                return False
            except (OSError, IOError) as e:
                logger.error(f"检查Session时发生IO错误 (账号 {account_id}): {e}")
                return False
            except Exception as e:
                logger.error(f"检查Session时出错 (账号 {account_id}): {e}")
                return False
            finally:
                try:
                    await page.close()
                    await context.close()
                except Exception:
                    pass

        try:
            return self.manager._run_async(_check())
        except Exception:
            return False


login_handler = LoginHandler()
