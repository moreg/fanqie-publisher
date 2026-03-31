"""
书籍API
"""
from flask import jsonify, request
from database.connection import get_session
from database.models import Book, Chapter, Account
from utils.logger import logger


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/books', methods=['GET'])
    def get_books():
        """获取书籍列表"""
        db = get_session()
        try:
            books = db.query(Book).all()
            return jsonify([b.to_dict() for b in books])
        finally:
            db.close()

    @api_bp.route('/books', methods=['POST'])
    def create_book():
        """创建书籍"""
        data = request.json
        db = get_session()
        try:
            book = Book(
                account_id=data.get('account_id'),
                fanqie_book_id=data.get('fanqie_book_id', ''),
                book_name=data.get('book_name', ''),
                local_folder=data.get('local_folder', ''),
                chapter_pattern=data.get('chapter_pattern', r"第(\d+)章\s+(.+)\.txt")
            )
            db.add(book)
            db.commit()
            return jsonify(book.to_dict()), 201
        except Exception as e:
            db.rollback()
            logger.error(f"创建书籍失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/books/<int:book_id>', methods=['PUT'])
    def update_book(book_id):
        """更新书籍"""
        data = request.json
        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                return jsonify({"error": "书籍不存在"}), 404

            if 'fanqie_book_id' in data:
                book.fanqie_book_id = data['fanqie_book_id']
            if 'book_name' in data:
                book.book_name = data['book_name']
            if 'local_folder' in data:
                book.local_folder = data['local_folder']
            if 'chapter_pattern' in data:
                book.chapter_pattern = data['chapter_pattern']
            if 'status' in data:
                book.status = data['status']

            db.commit()
            return jsonify(book.to_dict())
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/books/<int:book_id>', methods=['DELETE'])
    def delete_book(book_id):
        """删除书籍"""
        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if book:
                db.delete(book)
                db.commit()
                return jsonify({"success": True})
            return jsonify({"error": "书籍不存在"}), 404
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()
