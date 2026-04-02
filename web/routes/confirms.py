"""
发布确认API
"""
from flask import jsonify, request
from database.connection import get_session
from database.models import PublishConfirm, SystemConfig
from datetime import datetime
from utils.logger import logger


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/confirms', methods=['GET'])
    def get_confirms():
        """获取所有发布确认记录"""
        db = get_session()
        try:
            # 支持过滤状态
            status = request.args.get('status')
            query = db.query(PublishConfirm)

            if status:
                query = query.filter_by(status=status)
            else:
                # 默认只显示 pending 和 failed
                query = query.filter(PublishConfirm.status.in_(['pending', 'failed']))

            confirms = query.order_by(PublishConfirm.created_at.desc()).limit(50).all()
            return jsonify([c.to_dict() for c in confirms])
        finally:
            db.close()

    @api_bp.route('/confirms/<int:confirm_id>', methods=['GET'])
    def get_confirm(confirm_id):
        """获取单个确认记录"""
        db = get_session()
        try:
            confirm = db.query(PublishConfirm).filter_by(id=confirm_id).first()
            if not confirm:
                return jsonify({"error": "确认记录不存在"}), 404
            return jsonify(confirm.to_dict())
        finally:
            db.close()

    @api_bp.route('/confirms/<int:confirm_id>/cancel', methods=['POST'])
    def cancel_confirm(confirm_id):
        """取消确认"""
        db = get_session()
        try:
            confirm = db.query(PublishConfirm).filter_by(id=confirm_id).first()
            if not confirm:
                return jsonify({"error": "确认记录不存在"}), 404

            if confirm.status != "pending":
                return jsonify({"error": "只能取消待确认的记录"}), 400

            confirm.status = "cancelled"
            db.commit()
            return jsonify(confirm.to_dict())
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/confirms/<int:confirm_id>/retry', methods=['POST'])
    def retry_confirm(confirm_id):
        """重试确认"""
        db = get_session()
        try:
            confirm = db.query(PublishConfirm).filter_by(id=confirm_id).first()
            if not confirm:
                return jsonify({"error": "确认记录不存在"}), 404

            if confirm.status not in ["failed", "cancelled"]:
                return jsonify({"error": "只能重试失败或已取消的记录"}), 400

            # 重置状态并安排立即检查
            confirm.status = "pending"
            confirm.confirm_after = datetime.now()
            confirm.retry_count = 0
            confirm.error_message = None
            db.commit()
            return jsonify(confirm.to_dict())
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/confirms/stats', methods=['GET'])
    def get_confirm_stats():
        """获取确认统计"""
        db = get_session()
        try:
            pending = db.query(PublishConfirm).filter_by(status="pending").count()
            confirmed = db.query(PublishConfirm).filter_by(status="confirmed").count()
            failed = db.query(PublishConfirm).filter_by(status="failed").count()
            cancelled = db.query(PublishConfirm).filter_by(status="cancelled").count()

            return jsonify({
                "pending": pending,
                "confirmed": confirmed,
                "failed": failed,
                "cancelled": cancelled,
                "total": pending + confirmed + failed + cancelled
            })
        finally:
            db.close()

    @api_bp.route('/config/publish_confirm_delay', methods=['GET'])
    def get_confirm_delay():
        """获取发布确认延迟时间"""
        db = get_session()
        try:
            config = db.query(SystemConfig).filter_by(key="publish_confirm_delay").first()
            return jsonify({
                "delay_minutes": int(config.value) if config and config.value else 20,
                "description": config.description if config else "发布后等待确认的时间（分钟）"
            })
        finally:
            db.close()

    @api_bp.route('/config/publish_confirm_delay', methods=['PUT'])
    def update_confirm_delay():
        """更新发布确认延迟时间"""
        data = request.json
        delay_minutes = data.get('delay_minutes', 20)

        if not isinstance(delay_minutes, int) or delay_minutes < 1 or delay_minutes > 1440:
            return jsonify({"error": "延迟时间必须在1-1440分钟之间"}), 400

        db = get_session()
        try:
            config = db.query(SystemConfig).filter_by(key="publish_confirm_delay").first()
            if not config:
                config = SystemConfig(
                    key="publish_confirm_delay",
                    value=str(delay_minutes),
                    description="发布后等待确认的时间（分钟）"
                )
                db.add(config)
            else:
                config.value = str(delay_minutes)
                config.updated_at = datetime.now()

            db.commit()
            logger.info(f"更新发布确认延迟时间: {delay_minutes} 分钟")
            return jsonify({"success": True, "delay_minutes": delay_minutes})
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()
