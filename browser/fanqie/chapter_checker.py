#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
番茄小说章节检查器 - 检查远程章节是否已存在
"""
import asyncio
import re
from typing import Set, List, Optional

from playwright.async_api import Page

from config import FANQIE_BASE_URL
from browser.fanqie.exceptions import SessionExpiredException
from utils.logger import logger


class ChapterChecker:
    """检查番茄小说上的章节"""

    def __init__(self, page: Page):
        self.page = page

    async def get_published_chapters(self, fanqie_book_id: str) -> Set[str]:
        """
        获取番茄小说上已发布的章节标题集合

        Args:
            fanqie_book_id: 番茄书籍ID

        Returns:
            已发布章节标题的集合
        """
        url = f"{FANQIE_BASE_URL}/main/writer/chapter-manage/{fanqie_book_id}"
        logger.info(f"检查已发布章节: {url}")

        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # 检查是否被重定向到登录页
            if "login" in self.page.url.lower():
                raise SessionExpiredException("Session已过期，需要重新登录")

            # 检查页面是否显示错误
            page_text = await self.page.text_content("body")
            if "抱歉" in page_text or "不存在" in page_text:
                logger.warning("页面不存在，可能URL错误或Cookie已过期")
                return set()

            # 等待章节列表加载
            await asyncio.sleep(2)

            # 获取所有章节标题
            titles = await self._extract_chapter_titles()
            logger.info(f"番茄小说上共有 {len(titles)} 个章节")

            return titles

        except SessionExpiredException:
            raise
        except Exception as e:
            logger.error(f"获取已发布章节失败: {e}")
            return set()

    async def _extract_chapter_titles(self) -> Set[str]:
        """提取页面上的章节标题"""
        titles = set()

        # 尝试多种选择器
        selectors = [
            # 章节列表项
            "[class*='chapter-item'] [class*='title'], "
            "[class*='chapter-item'] [class*='name'], "
            "[class*='chapter'] [class*='title'], "
            ".chapter-list [class*='item'] [class*='title'], "
            "[class*='chapter-list'] [class*='name'], "
            "[class*='chapter'] [class*='chapter-name'], "
            # 表格形式
            "table [class*='chapter'] [class*='title'], "
            "table td[class*='name'], "
            "table td[class*='title'], "
            # 通用列表
            "li[class*='chapter'] [class*='title'], "
            "[class*='list'] [class*='chapter'] [class*='name'], "
            # 链接形式
            "a[class*='chapter']:not([href])",
        ]

        elements = []
        for selector in selectors:
            try:
                found = await self.page.query_selector_all(selector)
                if found:
                    elements = found
                    logger.debug(f"选择器 '{selector}' 找到 {len(found)} 个元素")
                    break
            except Exception:
                continue

        for el in elements:
            try:
                text = (await el.inner_text()).strip()
                # 清理标题
                text = self._clean_title(text)
                if text:
                    titles.add(text)
            except Exception:
                continue

        # 如果上述方式都没找到，尝试从页面所有文本中提取
        if not titles:
            titles = await self._extract_titles_from_text()

        return titles

    async def _extract_titles_from_text(self) -> Set[str]:
        """从页面文本中提取章节标题"""
        titles = set()

        # 尝试从页面源码中提取
        try:
            content = await self.page.content()

            # 匹配模式: 第X章 或 第X集
            chapter_patterns = [
                r'第[零一二三四五六七八九十百千万\d]+[章集话篇].*?(?=<|\n|$)',
                r'chapter["\s]*:[\s]*["\']([^"\']+)["\']',
                r'title["\s]*:[\s]*["\']([^"\']+)["\']',
            ]

            for pattern in chapter_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    cleaned = self._clean_title(match)
                    if cleaned and len(cleaned) > 2:
                        titles.add(cleaned)

        except Exception as e:
            logger.debug(f"从文本提取失败: {e}")

        return titles

    def _clean_title(self, title: str) -> str:
        """清理章节标题"""
        if not title:
            return ""

        # 移除多余空白
        title = ' '.join(title.split())

        # 移除常见后缀
        suffixes = [
            '审核通过', '待审核', '已发布', '草稿', '已删除',
            '[已发布]', '(已发布)', '[待审核]', '(待审核)'
        ]
        for suffix in suffixes:
            if suffix in title:
                title = title.replace(suffix, '').strip()

        return title.strip()[:200]  # 限制长度


async def check_chapters_exists(
    page: Page,
    fanqie_book_id: str,
    chapter_titles: List[str]
) -> dict:
    """
    检查章节是否已存在于番茄小说

    Args:
        page: Playwright页面对象
        fanqie_book_id: 番茄书籍ID
        chapter_titles: 待检查的章节标题列表

    Returns:
        {
            'published': {已发布的章节标题集合},
            'to_publish': [待发布的章节标题列表],
            'skipped': [已存在被跳过的章节标题列表]
        }
    """
    checker = ChapterChecker(page)

    try:
        # 获取番茄上已发布的章节
        published = await checker.get_published_chapters(fanqie_book_id)

        to_publish = []
        skipped = []

        for title in chapter_titles:
            # 标准化标题用于比较
            normalized = ChapterChecker(page)._clean_title(title)

            # 检查是否已存在（使用模糊匹配）
            is_exists = False
            for pub_title in published:
                if _titles_match(normalized, pub_title):
                    is_exists = True
                    break

            if is_exists:
                skipped.append(title)
            else:
                to_publish.append(title)

        logger.info(f"章节检查结果: 共{len(chapter_titles)}个, 已发布{len(published)}个, "
                    f"本次待发{len(to_publish)}个, 跳过{len(skipped)}个")

        return {
            'published': published,
            'to_publish': to_publish,
            'skipped': skipped
        }

    except Exception as e:
        logger.error(f"检查章节失败: {e}")
        return {
            'published': set(),
            'to_publish': chapter_titles,
            'skipped': []
        }


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
