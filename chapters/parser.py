import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from utils.file_helpers import read_file_content, count_words
from utils.logger import logger


@dataclass
class ChapterInfo:
    """解析后的章节信息"""
    chapter_number: int
    chapter_title: str
    file_path: str
    content: str
    word_count: int


class ChapterParser:
    """章节文件解析器"""

    def __init__(self, pattern: str = None):
        from config import DEFAULT_CHAPTER_PATTERN
        self.pattern = pattern or DEFAULT_CHAPTER_PATTERN

    def parse_filename(self, filename: str) -> Optional[tuple[int, str]]:
        """
        从文件名解析章节号和标题

        支持格式:
        - 第001章 风起云涌.txt
        - 第1章 风起云涌.txt
        - 001-风起云涌.txt
        - 001_风起云涌.txt
        - 第一章.txt
        - 第1章.txt

        Returns:
            (chapter_number, chapter_title) 或 None
        """
        
        def chinese_to_num(chinese: str) -> int:
            """中文数字转阿拉伯数字"""
            num_map = {
                '零': 0, '〇': 0, '一': 1, '二': 2, '三': 3, '四': 4,
                '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
                '十': 10, '百': 100, '千': 1000,
            }
            result = 0
            temp = 0
            for c in chinese:
                if c in num_map:
                    if num_map[c] == 10:
                        if temp == 0:
                            temp = 1
                        result += temp * 10
                        temp = 0
                    elif num_map[c] == 100:
                        if temp == 0:
                            temp = 1
                        result += temp * 100
                        temp = 0
                    elif num_map[c] == 1000:
                        if temp == 0:
                            temp = 1
                        result += temp * 1000
                        temp = 0
                    else:
                        temp = num_map[c]
            result += temp
            return result if result > 0 else None
        
        # 主正则
        match = re.match(self.pattern, filename)
        if match:
            return int(match.group(1)), match.group(2).strip()

        # 回退正则列表
        fallback_patterns = [
            r"第(\d+)[章节]\s*(.*)\.txt$",
            r"(\d+)[-_]\s*(.+)\.txt$",
            r"(\d+)\s+(.+)\.txt$",
            r"第(\d+)章(.+)\.txt$",
            r"第([零〇一二三四五六七八九十百千]+)[章节]\s*(.*)\.txt$",
            r"第([零〇一二三四五六七八九十百千]+)[章节]\.txt$",
            r"(\d+)\.txt$",
        ]
        for pat in fallback_patterns:
            match = re.match(pat, filename, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) >= 1:
                    num_str = groups[0]
                    title = groups[1] if len(groups) > 1 and groups[1] else f"第{num_str}章"
                    
                    # 尝试转换中文数字
                    if num_str and any(c in '零〇一二三四五六七八九十百千' for c in num_str):
                        num = chinese_to_num(num_str)
                        if num is not None:
                            return num, title
                    
                    # 尝试转换阿拉伯数字
                    try:
                        num = int(num_str)
                        return num, title
                    except ValueError:
                        pass

        return None

    def parse_file(self, file_path: str) -> Optional[ChapterInfo]:
        """解析一个章节文件"""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return None

        if not path.name.endswith(".txt"):
            return None

        parsed = self.parse_filename(path.name)
        if parsed is None:
            logger.warning(f"无法解析文件名: {path.name}")
            return None

        chapter_number, chapter_title = parsed

        try:
            content = read_file_content(str(path))
            word_count = count_words(content)
        except Exception as e:
            logger.error(f"读取文件失败 {path}: {e}")
            return None

        return ChapterInfo(
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            file_path=str(path),
            content=content,
            word_count=word_count,
        )
