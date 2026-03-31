"""
调度API
"""
from flask import jsonify, request
from database.connection import get_session
from database.models import Schedule
from utils.logger import logger


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/schedules', methods=['GET'])
    def get_schedules():
        """获取调度列表"""
        db = get_session()
        try:
            schedules = db.query(Schedule).all()
            return jsonify([s.to_dict() for s in schedules])
        finally:
            db.close()

    @api_bp.route('/schedules', methods=['POST'])
    def create_schedule():
        """创建调度"""
        data = request.json
        db = get_session()
        try:
            schedule = Schedule(
                book_id=data.get('book_id'),
                cron_expression=data.get('cron_expression', '0 8,20 * * *'),
                chapters_per_run=data.get('chapters_per_run', 1)
            )
            db.add(schedule)
            db.commit()
            return jsonify(schedule.to_dict()), 201
        except Exception as e:
            db.rollback()
            logger.error(f"创建调度失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/schedules/<int:schedule_id>', methods=['PUT'])
    def update_schedule(schedule_id):
        """更新调度"""
        data = request.json
        db = get_session()
        try:
            schedule = db.query(Schedule).filter_by(id=schedule_id).first()
            if not schedule:
                return jsonify({"error": "调度不存在"}), 404

            if 'is_active' in data:
                schedule.is_active = data['is_active']
            if 'cron_expression' in data:
                schedule.cron_expression = data['cron_expression']
            if 'chapters_per_run' in data:
                schedule.chapters_per_run = data['chapters_per_run']

            db.commit()
            return jsonify(schedule.to_dict())
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/schedules/<int:schedule_id>', methods=['DELETE'])
    def delete_schedule(schedule_id):
        """删除调度"""
        db = get_session()
        try:
            schedule = db.query(Schedule).filter_by(id=schedule_id).first()
            if schedule:
                db.delete(schedule)
                db.commit()
                return jsonify({"success": True})
            return jsonify({"error": "调度不存在"}), 404
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()
