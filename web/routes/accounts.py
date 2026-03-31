"""
账号API
"""
from flask import jsonify, request
from database.connection import get_session
from database.models import Account
from utils.logger import logger


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/accounts', methods=['GET'])
    def get_accounts():
        """获取账号列表"""
        db = get_session()
        try:
            accounts = db.query(Account).all()
            return jsonify([a.to_dict() for a in accounts])
        finally:
            db.close()

    @api_bp.route('/accounts', methods=['POST'])
    def create_account():
        """创建账号"""
        data = request.json
        db = get_session()
        try:
            account = Account(
                name=data.get('name', ''),
                phone=data.get('phone', ''),
                cookies=data.get('cookies'),
                status='active' if data.get('cookies') else 'inactive'
            )
            db.add(account)
            db.commit()
            return jsonify(account.to_dict()), 201
        except Exception as e:
            db.rollback()
            logger.error(f"创建账号失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/accounts/<int:account_id>', methods=['PUT'])
    def update_account(account_id):
        """更新账号"""
        data = request.json
        db = get_session()
        try:
            account = db.query(Account).filter_by(id=account_id).first()
            if not account:
                return jsonify({"error": "账号不存在"}), 404

            if 'name' in data:
                account.name = data['name']
            if 'phone' in data:
                account.phone = data['phone']
            if 'cookies' in data:
                account.cookies = data['cookies']
                if data['cookies']:
                    account.status = 'active'
            if 'status' in data:
                account.status = data['status']

            db.commit()
            return jsonify(account.to_dict())
        except Exception as e:
            db.rollback()
            logger.error(f"更新账号失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/accounts/<int:account_id>', methods=['DELETE'])
    def delete_account(account_id):
        """删除账号"""
        db = get_session()
        try:
            account = db.query(Account).filter_by(id=account_id).first()
            if account:
                db.delete(account)
                db.commit()
                return jsonify({"success": True})
            return jsonify({"error": "账号不存在"}), 404
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()
