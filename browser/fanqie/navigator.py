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

    def _extract_status_from_element(self, el) -> str:
        """从书籍元素中提取状态（从标签/badge中查找）"""
        try:
            # 先检查是否有表示"完结"或"隐藏"的标签
            # 尝试查找所有可能的状态标签
            status_selectors = [
                "span", "div", "em", "strong", "label",
                "[class*='tag']", "[class*='badge']", "[class*='status']",
                "[class*='label']", "[class*='state']", "[class*='type']",
                "[class*='completed']", "[class*='ended']", "[class*='finished']",
                "[class*='hidden']", "[class*='gray']", "[class*='grey']",
                "[class*='disabled']", "[class*='inactive']"
            ]

            for sel in status_selectors:
                status_els = el.query_selector_all(sel)
                for status_el in status_els:
                    # 获取元素的class属性
                    el_class = (status_el.get_attribute("class") or "").lower()
                    el_style = (status_el.get_attribute("style") or "").lower()

                    # 获取文本内容
                    text = (status_el.inner_text() or "").strip()

                    # 检查是否灰色/禁用状态的class
                    if 'gray' in el_class or 'grey' in el_class or 'disabled' in el_class:
                        if '完结' in text or 'end' in el_class or 'finish' in el_class:
                            return 'completed'
                        if '隐藏' in text or '私密' in text or 'hide' in el_class:
                            return 'hidden'

                    # 检查class中直接包含状态
                    if 'completed' in el_class or 'finished' in el_class or 'ended' in el_class:
                        return 'completed'
                    if 'hidden' in el_class or 'private' in el_class:
                        return 'hidden'

                    # 检查文本内容中的状态关键词
                    if '完结' in text or '已完结' in text:
                        return 'completed'
                    if '隐藏' in text or '私密' in text or '已隐藏' in text:
                        return 'hidden'
                    if '签约' in text:
                        return 'signed'
                    if '连载' in text or '更新' in text or '连载中' in text:
                        return 'serializing'

            return 'active'
        except Exception:
            return 'active'

    def _extract_status_from_name(self, name: str) -> str:
        """从书名中提取状态"""
        if not name:
            return 'unknown'
        if '已完结' in name:
            return 'completed'
        if '已隐藏' in name or '已私密' in name:
            return 'hidden'
        if '已签约' in name:
            return 'signed'
        if '连载中' in name:
            return 'serializing'
        return 'active'

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
        """获取当前账号的书籍列表（过滤掉完结和隐藏的书籍）"""
        await self.navigator.goto_book_manage()

        books_dict = {}
        filtered_count = 0  # 记录被过滤的书籍数量
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
                    # 先从元素中提取状态（从标签/badge中查找）
                    element_status = self._extract_status_from_element(el)

                    # 获取书名
                    name_el = await el.query_selector(
                        "[class*='title']:not([class*='sub']):not([class*='desc']), "
                        "[class*='name']:not([class*='sub']):not([class*='desc']), "
                        "h1, h2, h3, h4, span:first-child"
                    )
                    raw_name = (await name_el.inner_text()).strip() if name_el else ""
                    # 也从书名中提取状态
                    name_status = self._extract_status_from_name(raw_name)
                    name = self._clean_book_name(raw_name)

                    # 综合状态：优先使用元素状态，否则使用书名状态
                    final_status = element_status if element_status != 'active' else name_status

                    # 过滤掉已完结和已隐藏的书籍
                    if final_status in ['completed', 'hidden']:
                        filtered_count += 1
                        logger.info(f"跳过已完结/已隐藏书籍: {name} (状态: {final_status})")
                        continue

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

                    books_dict[name] = {"fanqie_book_id": book_id, "book_name": name, "book_status": final_status}
                    logger.info(f"书籍: {name} -> ID: {book_id}, 状态: {final_status}")

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

        logger.info(f"获取到 {len(books_dict)} 本书籍（已过滤 {filtered_count} 本完结/隐藏书籍）")
        return list(books_dict.values())
