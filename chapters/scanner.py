import os
from pathlib import Path
from typing import Optional

from chapters.parser import ChapterParser, ChapterInfo
from utils.logger import logger


class ChapterScanner:
    """扫描本地文件夹，发现和排序章节文件"""

    def __init__(self, chapter_pattern: str = None):
        self.parser = ChapterParser(chapter_pattern)

    def scan_folder(self, folder_path: str) -> list[ChapterInfo]:
        """
        扫描文件夹中的所有章节文件

        Args:
            folder_path: 本地文件夹路径

        Returns:
            按章节号排序的 ChapterInfo 列表
        """
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            logger.error(f"文件夹不存在或不是目录: {folder_path}")
            return []

        chapters = []
        for file_path in sorted(folder.iterdir()):
            if file_path.is_file() and file_path.name.endswith(".txt"):
                chapter = self.parser.parse_file(str(file_path))
                if chapter:
                    chapters.append(chapter)

        # 按章节号排序
        chapters.sort(key=lambda c: c.chapter_number)
        logger.info(f"从 {folder_path} 扫描到 {len(chapters)} 个章节")
        return chapters

    def scan_new_chapters(self, folder_path: str, published_numbers: set[int]) -> list[ChapterInfo]:
        """
        扫描文件夹，只返回尚未发布的章节

        Args:
            folder_path: 本地文件夹路径
            published_numbers: 已发布的章节号集合

        Returns:
            未发布的 ChapterInfo 列表（按章节号排序）
        """
        all_chapters = self.scan_folder(folder_path)
        new_chapters = [c for c in all_chapters if c.chapter_number not in published_numbers]
        logger.info(f"发现 {len(new_chapters)} 个未发布的章节")
        return new_chapters
