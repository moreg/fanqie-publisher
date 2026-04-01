"""
待发布任务API
"""
from flask import jsonify, request
from database.connection import get_session
from database.models import PendingTask, Chapter, Book
from datetime import datetime
from utils.logger import logger


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/tasks', methods=['GET'])
    def get_tasks():
        """获取待发布任务"""
        db = get_session()
        try:
            tasks = db.query(PendingTask).order_by(
                PendingTask.scheduled_time
            ).all()
            return jsonify([t.to_dict() for t in tasks])
        finally:
            db.close()

    @api_bp.route('/tasks', methods=['POST'])
    def create_task():
        """创建待发布任务"""
        data = request.json
        db = get_session()
        try:
            scheduled_time = data.get('scheduled_time')
            if scheduled_time:
                scheduled_time = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
            else:
                scheduled_time = datetime.now()

            task = PendingTask(
                chapter_id=data.get('chapter_id'),  # 可为空
                book_id=data.get('book_id'),
                chapter_file=data.get('chapter_file'),  # 本地文件路径
                chapter_title=data.get('chapter_title'),  # 本地章节标题
                scheduled_time=scheduled_time,
                status='pending'
            )
            db.add(task)
            db.commit()
            return jsonify(task.to_dict()), 201
        except Exception as e:
            db.rollback()
            logger.error(f"创建任务失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/tasks/<int:task_id>', methods=['PUT'])
    def update_task(task_id):
        """更新任务"""
        data = request.json
        db = get_session()
        try:
            task = db.query(PendingTask).filter_by(id=task_id).first()
            if not task:
                return jsonify({"error": "任务不存在"}), 404

            if 'scheduled_time' in data:
                scheduled_time = data.get('scheduled_time')
                if scheduled_time:
                    task.scheduled_time = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))

            db.commit()
            return jsonify(task.to_dict())
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/tasks/<int:task_id>', methods=['DELETE'])
    def delete_task(task_id):
        """删除任务"""
        db = get_session()
        try:
            task = db.query(PendingTask).filter_by(id=task_id).first()
            if task:
                db.delete(task)
                db.commit()
                return jsonify({"success": True})
            return jsonify({"error": "任务不存在"}), 404
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/tasks/<int:task_id>/cancel', methods=['POST'])
    def cancel_task(task_id):
        """取消任务"""
        db = get_session()
        try:
            task = db.query(PendingTask).filter_by(id=task_id).first()
            if task:
                task.status = 'cancelled'
                db.commit()
                return jsonify(task.to_dict())
            return jsonify({"error": "任务不存在"}), 404
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()
