"""
章节API
"""
import re
import os
from flask import jsonify, request
from database.connection import get_session
from database.models import Book, Chapter
from utils.logger import logger
from utils.file_helpers import count_words


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/books/<int:book_id>/chapters', methods=['GET'])
    def get_chapters(book_id):
        """获取书籍的章节列表"""
        db = get_session()
        try:
            chapters = db.query(Chapter).filter_by(book_id=book_id).order_by(Chapter.chapter_number).all()
            return jsonify([c.to_dict() for c in chapters])
        finally:
            db.close()

    @api_bp.route('/books/<int:book_id>/chapters/scan', methods=['POST'])
    def scan_chapters(book_id):
        """扫描本地文件夹获取章节"""
        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                return jsonify({"error": "书籍不存在"}), 404

            if not os.path.exists(book.local_folder):
                return jsonify({"error": "文件夹不存在"}), 400

            # 获取已存在的章节
            existing = {c.chapter_number for c in book.chapters}
            added = 0

            # 扫描文件
            pattern = re.compile(book.chapter_pattern)
            for filename in os.listdir(book.local_folder):
                if not filename.endswith('.txt'):
                    continue

                match = pattern.match(filename)
                if not match:
                    continue

                chapter_number = int(match.group(1))
                chapter_title = match.group(2)

                if chapter_number in existing:
                    continue

                # 获取字数
                filepath = os.path.join(book.local_folder, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    word_count = count_words(content)
                except:
                    word_count = 0

                chapter = Chapter(
                    book_id=book_id,
                    chapter_number=chapter_number,
                    chapter_title=chapter_title,
                    file_path=filepath,
                    word_count=word_count,
                    status='pending'
                )
                db.add(chapter)
                added += 1

            db.commit()
            return jsonify({"added": added})
        except Exception as e:
            db.rollback()
            logger.error(f"扫描章节失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/chapters/<int:chapter_id>', methods=['PUT'])
    def update_chapter(chapter_id):
        """更新章节"""
        data = request.json
        db = get_session()
        try:
            chapter = db.query(Chapter).filter_by(id=chapter_id).first()
            if not chapter:
                return jsonify({"error": "章节不存在"}), 404

            if 'status' in data:
                chapter.status = data['status']

            db.commit()
            return jsonify(chapter.to_dict())
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()
