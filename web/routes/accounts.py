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

            # 如果有 Cookie，自动同步书籍
            if account.cookies:
                sync_books_for_account(account.id, db)

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

            cookies_updated = False
            if 'name' in data:
                account.name = data['name']
            if 'phone' in data:
                account.phone = data['phone']
            if 'cookies' in data:
                old_cookies = account.cookies
                account.cookies = data['cookies']
                if data['cookies']:
                    account.status = 'active'
                    if old_cookies != data['cookies']:  # Cookie 发生变化
                        cookies_updated = True
            if 'status' in data:
                account.status = data['status']

            db.commit()

            # 如果 Cookie 更新了，自动同步书籍
            if cookies_updated:
                sync_books_for_account(account_id, db)

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


def sync_books_for_account(account_id: int, db):
    """同步账号的书籍列表"""
    from database.models import Book
    from browser.manager import browser_manager

    try:
        async def _sync():
            from browser.fanqie.navigator import AsyncBookManager
            context = await browser_manager._async_create_context_from_session(account_id)
            if context is None:
                logger.warning(f"账号 {account_id} 无法创建浏览器上下文")
                return 0

            page = await context.new_page()
            try:
                manager = AsyncBookManager(page)
                books_data = await manager.get_book_list()

                synced = 0
                try:
                    for book_info in books_data:
                        fanqie_id = book_info.get('fanqie_book_id', '')
                        if not fanqie_id:
                            continue

                        existing = db.query(Book).filter_by(
                            account_id=account_id,
                            fanqie_book_id=fanqie_id
                        ).first()

                        if not existing:
                            new_book = Book(
                                account_id=account_id,
                                fanqie_book_id=fanqie_id,
                                book_name=book_info.get('book_name', ''),
                                local_folder='',
                                chapter_pattern=r"第(\d+)章\s+(.+)\.txt"
                            )
                            db.add(new_book)
                            synced += 1
                        else:
                            existing.book_name = book_info.get('book_name', existing.book_name)

                    db.commit()
                    logger.info(f"账号 {account_id} 同步了 {synced} 本新书籍")
                    return synced
                except Exception as e:
                    db.rollback()
                    logger.error(f"同步书籍数据库操作失败: {e}")
                    raise
            finally:
                await page.close()
                await context.close()

        return browser_manager._run_async(_sync())
    except Exception as e:
        logger.error(f"同步账号 {account_id} 书籍失败: {e}")
        return 0
