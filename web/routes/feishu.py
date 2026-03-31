"""
飞书配置API
"""
from flask import jsonify, request
from database.connection import get_session
from database.models import FeishuConfig
from utils.logger import logger
from utils.feishu import FeishuConfig as FeishuConfigModel, get_feishu_notifier


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/feishu/config', methods=['GET'])
    def get_feishu_config():
        """获取飞书配置"""
        db = get_session()
        try:
            config = db.query(FeishuConfig).first()
            if not config:
                return jsonify({"enabled": False})
            return jsonify(config.to_dict())
        finally:
            db.close()

    @api_bp.route('/feishu/config', methods=['POST'])
    def save_feishu_config():
        """保存飞书配置"""
        data = request.json
        db = get_session()
        try:
            config = db.query(FeishuConfig).first()
            if not config:
                config = FeishuConfig()
                db.add(config)

            config.webhook_url = data.get('webhook_url', '')
            config.enabled = data.get('enabled', False)
            config.app_id = data.get('app_id', '')
            config.app_secret = data.get('app_secret', '')

            db.commit()

            # 更新全局通知器
            notifier = get_feishu_notifier()
            notifier.set_config(FeishuConfigModel(
                app_id=config.app_id or '',
                app_secret=config.app_secret or '',
                webhook_url=config.webhook_url or '',
                enabled=config.enabled
            ))

            return jsonify(config.to_dict())
        except Exception as e:
            db.rollback()
            logger.error(f"保存飞书配置失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/feishu/test', methods=['POST'])
    def test_feishu():
        """测试飞书通知"""
        try:
            notifier = get_feishu_notifier()
            if not notifier.is_enabled():
                return jsonify({"success": False, "message": "飞书通知未启用"})

            success = notifier.send_publish_success(
                book_name="测试书籍",
                chapter_title="第一章 测试章节"
            )

            return jsonify({"success": success})
        except Exception as e:
            logger.error(f"测试飞书通知失败: {e}")
            return jsonify({"success": False, "message": str(e)})
