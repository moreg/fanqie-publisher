"""
发布日志API
"""
from flask import jsonify, request
from database.connection import get_session
from database.models import PublishLog
from utils.logger import logger


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/logs', methods=['GET'])
    def get_logs():
        """获取发布日志"""
        db = get_session()
        try:
            limit = request.args.get('limit', 100, type=int)
            logs = db.query(PublishLog).order_by(
                PublishLog.created_at.desc()
            ).limit(limit).all()
            return jsonify([l.to_dict() for l in logs])
        finally:
            db.close()

    @api_bp.route('/logs/book/<int:book_id>', methods=['GET'])
    def get_book_logs(book_id):
        """获取指定书籍的发布日志"""
        db = get_session()
        try:
            logs = db.query(PublishLog).join(Chapter).filter(
                Chapter.book_id == book_id
            ).order_by(PublishLog.created_at.desc()).limit(50).all()
            return jsonify([l.to_dict() for l in logs])
        finally:
            db.close()

    @api_bp.route('/logs/stats', methods=['GET'])
    def get_stats():
        """获取统计数据"""
        db = get_session()
        try:
            from database.models import Chapter, PublishLog
            from sqlalchemy import func

            # 章节统计
            total_chapters = db.query(func.count(Chapter.id)).scalar()
            published_chapters = db.query(func.count(Chapter.id)).filter(
                Chapter.status == 'published'
            ).scalar()

            # 发布统计
            total_publishes = db.query(func.count(PublishLog.id)).scalar()
            successful_publishes = db.query(func.count(PublishLog.id)).filter(
                PublishLog.status == 'success'
            ).scalar()
            failed_publishes = db.query(func.count(PublishLog.id)).filter(
                PublishLog.status == 'failed'
            ).scalar()

            return jsonify({
                'total_chapters': total_chapters or 0,
                'published_chapters': published_chapters or 0,
                'total_publishes': total_publishes or 0,
                'successful_publishes': successful_publishes or 0,
                'failed_publishes': failed_publishes or 0
            })
        finally:
            db.close()
