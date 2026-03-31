from datetime import datetime
from typing import Optional, List

from database.connection import safe_session
from database.models import Chapter, Book
from chapters.scanner import ChapterScanner
from utils.logger import logger


class ChapterTracker:
    """章节发布追踪器 - 同步本地文件与数据库"""

    def sync_chapters(self, book_id: int) -> int:
        """
        同步本地文件夹的章节到数据库

        Returns:
            新增章节数
        """
        with safe_session() as session:
            book = session.query(Book).filter_by(id=book_id).first()
            if not book:
                logger.error(f"书籍 {book_id} 不存在")
                return 0

            scanner = ChapterScanner(book.chapter_pattern)
            local_chapters = scanner.scan_folder(book.local_folder)

            existing = {
                c.chapter_number: c
                for c in session.query(Chapter).filter_by(book_id=book_id).all()
            }

            new_count = 0
            for ch_info in local_chapters:
                if ch_info.chapter_number not in existing:
                    chapter = Chapter(
                        book_id=book_id,
                        chapter_number=ch_info.chapter_number,
                        chapter_title=ch_info.chapter_title,
                        file_path=ch_info.file_path,
                        word_count=ch_info.word_count,
                        status="pending",
                    )
                    session.add(chapter)
                    new_count += 1
                else:
                    existing_ch = existing[ch_info.chapter_number]
                    if existing_ch.status == "pending":
                        existing_ch.file_path = ch_info.file_path
                        existing_ch.word_count = ch_info.word_count
                        existing_ch.chapter_title = ch_info.chapter_title

            logger.info(f"同步书籍 {book_id}: 新增 {new_count} 章节")
            return new_count

    def get_next_pending_chapters(self, book_id: int, count: int = 1) -> List[Chapter]:
        """获取下N个待发布章节"""
        with safe_session(auto_commit=False) as session:
            chapters = (
                session.query(Chapter)
                .filter_by(book_id=book_id, status="pending")
                .order_by(Chapter.chapter_number)
                .limit(count)
                .all()
            )
            result = []
            for ch in chapters:
                session.expunge(ch)
                result.append(ch)
            return result

    def mark_chapter_publishing(self, chapter_id: int) -> bool:
        """标记章节为发布中"""
        with safe_session() as session:
            chapter = session.query(Chapter).filter_by(id=chapter_id).first()
            if chapter:
                chapter.status = "publishing"
                return True
            return False

    def mark_chapter_published(self, chapter_id: int, fanqie_chapter_id: str = None) -> bool:
        """标记章节为已发布"""
        with safe_session() as session:
            chapter = session.query(Chapter).filter_by(id=chapter_id).first()
            if chapter:
                chapter.status = "published"
                chapter.published_at = datetime.now()
                if fanqie_chapter_id:
                    chapter.fanqie_chapter_id = fanqie_chapter_id
                return True
            return False

    def mark_chapter_failed(self, chapter_id: int, error_message: str) -> bool:
        """标记章节发布失败"""
        with safe_session() as session:
            chapter = session.query(Chapter).filter_by(id=chapter_id).first()
            if chapter:
                chapter.status = "failed"
                chapter.error_message = error_message
                chapter.retry_count += 1
                return True
            return False

    def reset_failed_chapter(self, chapter_id: int) -> bool:
        """重置失败章节为待发布"""
        with safe_session() as session:
            chapter = session.query(Chapter).filter_by(id=chapter_id).first()
            if chapter and chapter.status == "failed":
                chapter.status = "pending"
                chapter.error_message = None
                chapter.retry_count = 0
                return True
            return False

    def reset_stale_publishing_chapters(self, timeout_seconds: int = 300) -> int:
        """重置超时未完成的 publishing 状态章节

        Args:
            timeout_seconds: 超时秒数，默认5分钟
        """
        from datetime import timedelta
        with safe_session() as session:
            cutoff_time = datetime.now() - timedelta(seconds=timeout_seconds)
            stale_chapters = (
                session.query(Chapter)
                .filter(
                    Chapter.status == "publishing",
                    Chapter.created_at < cutoff_time
                )
                .all()
            )
            count = 0
            for chapter in stale_chapters:
                chapter.status = "pending"
                chapter.error_message = f"发布超时（超过{timeout_seconds}秒），已自动重置"
                count += 1
            if count > 0:
                logger.warning(f"已重置 {count} 个超时未完成的章节")
            return count


chapter_tracker = ChapterTracker()
