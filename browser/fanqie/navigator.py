import asyncio
import re
from typing import Optional

from playwright.async_api import Page

from config import FANQIE_BOOK_MANAGE_URL, FANQIE_BASE_URL
from browser.fanqie.selectors import BookManagePage
from browser.fanqie.exceptions import SessionExpiredException
from utils.logger import logger


class AsyncNavigator:
    """番茄小说后台页面导航 - 异步版本"""

    def __init__(self, page: Page):
        self.page = page

    async def goto_book_manage(self):
        """导航到书籍管理页"""
        logger.info("导航到书籍管理页...")
        await self.page.goto(FANQIE_BOOK_MANAGE_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)  # 等待SPA加载
        self._check_login_redirect()

    def _check_login_redirect(self):
        """检查是否被重定向到登录页"""
        current_url = self.page.url
        if "login" in current_url.lower() or current_url.rstrip("/").endswith("/writer"):
            raise SessionExpiredException("Session已过期，需要重新登录")


class AsyncBookManager:
    """从番茄后台获取书籍信息 - 异步版本"""

    def __init__(self, page: Page):
        self.page = page
        self.navigator = AsyncNavigator(page)

    def _extract_id_from_href(self, href: str) -> str:
        """从href中提取书籍ID"""
        if not href:
            return ""

        # 尝试多种模式
        patterns = [
            r'/book/(\d+)',
            r'/novel/(\d+)',
            r'/work/(\d+)',
            r'id=(\d+)',
            r'bookId=(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, href)
            if match:
                book_id = match.group(1)
                if len(book_id) > 5:
                    return book_id

        # 查找任何6位以上的数字
        numbers = re.findall(r'\d{6,}', href)
        if numbers:
            return numbers[0]

        return ""

    def _clean_book_name(self, name: str) -> str:
        """清理书名"""
        if not name:
            return ""
        name = name.replace('\\n', ' ').replace('/n', ' ').replace('\\\\n', ' ')
        name = ' '.join(name.split())
        suffixes = ['征文作品', '已隐藏', '已签约', '已完结', '连载中', '已删除']
        for suffix in suffixes:
            if suffix in name:
                name = name.replace(suffix, '').strip()
        return name.strip()[:100]

    async def get_book_list(self) -> list[dict]:
        """获取当前账号的书籍列表"""
        await self.navigator.goto_book_manage()

        books_dict = {}
        try:
            # 尝试多种选择器
            selectors = [
                ".book-item", ".work-item", ".novel-item",
                "[class*='work-item']", "[class*='book-item'][class*='item']",
                "li[class*='item']", "div[class*='work']",
            ]

            book_elements = []
            for sel in selectors:
                found = await self.page.query_selector_all(sel)
                if found:
                    book_elements = found
                    logger.info(f"使用选择器 '{sel}' 找到 {len(found)} 个元素")
                    break

            # 处理元素
            seen_names = set()
            idx = 0
            for el in book_elements:
                try:
                    # 获取书名
                    name_el = await el.query_selector(
                        "[class*='title']:not([class*='sub']):not([class*='desc']), "
                        "[class*='name']:not([class*='sub']):not([class*='desc']), "
                        "h1, h2, h3, h4, span:first-child"
                    )
                    raw_name = (await name_el.inner_text()).strip() if name_el else ""
                    name = self._clean_book_name(raw_name)

                    if not name:
                        continue

                    if name in seen_names:
                        continue
                    seen_names.add(name)

                    # 获取书籍ID
                    book_id = ""

                    # 方式1: 从链接获取
                    link_el = await el.query_selector("a[href]")
                    if link_el:
                        href = await link_el.get_attribute("href") or ""
                        book_id = self._extract_id_from_href(href)
                        logger.debug(f"从链接提取: {href} -> {book_id}")

                    # 方式2: 从元素属性获取
                    if not book_id:
                        for attr in ['data-book-id', 'data-id', 'data-work-id', 'data-novel-id', 'id']:
                            val = await el.get_attribute(attr) or ""
                            if val and len(val) > 5 and val.isdigit():
                                book_id = val
                                logger.debug(f"从属性提取: {attr}={val}")
                                break

                    # 方式3: 使用索引
                    if not book_id:
                        book_id = f"book_{idx}"
                        idx += 1

                    books_dict[name] = {"fanqie_book_id": book_id, "book_name": name}
                    logger.info(f"书籍: {name} -> ID: {book_id}")

                except Exception as e:
                    logger.warning(f"解析书籍元素失败: {e}")
                    continue

            # 如果没找到，尝试直接搜索页面中的所有链接
            if not books_dict:
                logger.info("尝试从所有链接中提取书籍...")
                links = await self.page.query_selector_all("a[href]")
                for link in links:
                    try:
                        href = await link.get_attribute("href") or ""
                        book_id = self._extract_id_from_href(href)
                        if book_id:
                            text = (await link.inner_text()).strip()
                            name = self._clean_book_name(text)
                            if name and name not in books_dict:
                                books_dict[name] = {"fanqie_book_id": book_id, "book_name": name}
                                logger.info(f"从链接找到: {name} -> {book_id}")
                    except Exception:
                        continue

        except Exception as e:
            logger.error(f"获取书籍列表失败: {e}")

        logger.info(f"获取到 {len(books_dict)} 本书籍")
        return list(books_dict.values())
