"""
书籍API
"""
import os
import re
from flask import jsonify, request
from database.connection import get_session
from database.models import Book, Chapter, Account, PendingTask, PublishLog
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

    @api_bp.route('/books/sync/<int:account_id>', methods=['POST'])
    def sync_books_from_fanqie(account_id):
        """从番茄网站同步书籍到数据库"""
        db = get_session()
        try:
            account = db.query(Account).filter_by(id=account_id).first()
            if not account:
                return jsonify({"error": "账号不存在"}), 404

            if not account.cookies and not account.session_file:
                return jsonify({"error": "账号没有有效的Cookie或Session"}), 400

            # 调用浏览器获取书籍列表
            from browser.manager import browser_manager

            async def _sync():
                from browser.fanqie.navigator import AsyncBookManager
                context = await browser_manager._async_create_context_from_session(account_id)
                if context is None:
                    return {"error": "无法创建浏览器上下文"}

                page = await context.new_page()
                try:
                    manager = AsyncBookManager(page)
                    books_data = await manager.get_book_list()

                    # 同步到数据库
                    synced_count = 0
                    for book_info in books_data:
                        # 检查是否已存在
                        existing = db.query(Book).filter_by(
                            account_id=account_id,
                            fanqie_book_id=book_info.get('fanqie_book_id', '')
                        ).first()

                        if not existing:
                            new_book = Book(
                                account_id=account_id,
                                fanqie_book_id=book_info.get('fanqie_book_id', ''),
                                book_name=book_info.get('book_name', ''),
                                local_folder='',
                                chapter_pattern=r"第(\d+)章\s+(.+)\.txt",
                                book_status=book_info.get('book_status', 'active')
                            )
                            db.add(new_book)
                            synced_count += 1
                        else:
                            # 更新书名和状态
                            existing.book_name = book_info.get('book_name', existing.book_name)
                            existing.book_status = book_info.get('book_status', 'active')

                    db.commit()
                    logger.info(f"成功同步 {synced_count} 本新书籍到账号 {account_id}")
                    return {"success": True, "synced": synced_count, "total": len(books_data)}
                finally:
                    await page.close()
                    await context.close()

            result = browser_manager._run_async(_sync())
            return jsonify(result)

        except Exception as e:
            db.rollback()
            logger.error(f"同步书籍失败: {e}")
            return jsonify({"error": str(e)}), 500
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

    @api_bp.route('/local-books', methods=['GET'])
    def get_local_books():
        """获取本地书籍列表（扫描本地文件夹）"""
        db = get_session()
        try:
            books = db.query(Book).filter(
                Book.local_folder != '',
                Book.local_folder.isnot(None)
            ).all()

            result = []
            for book in books:
                folder = book.local_folder
                if not folder or not os.path.exists(folder):
                    result.append({
                        "id": book.id,
                        "book_name": book.book_name,
                        "local_folder": folder,
                        "account_name": book.account.name if book.account else None,
                        "exists": False,
                        "chapters": [],
                        "total_chapters": 0,
                        "total_words": 0,
                        "error": "文件夹不存在" if folder else "未设置本地路径"
                    })
                    continue

                # 扫描文件夹中的 txt 文件
                chapters = []
                total_words = 0
                try:
                    files = os.listdir(folder)
                    txt_files = [f for f in files if f.endswith('.txt')]

                    for txt_file in txt_files:
                        file_path = os.path.join(folder, txt_file)
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                word_count = len(content)
                                total_words += word_count

                            # 解析章节名
                            match = re.search(r'第(\d+)章\s+(.+)', txt_file)
                            if match:
                                chapter_number = int(match.group(1))
                                chapter_title = match.group(2).replace('.txt', '')
                            else:
                                chapter_number = len(chapters) + 1
                                chapter_title = txt_file.replace('.txt', '')

                            # 查询章节发布状态
                            publish_status = 'none'  # none: 未发布, pending: 待发布, published: 已发布, failed: 发布失败

                            # 查询该章节是否有成功的发布记录
                            success_task = db.query(PendingTask).filter(
                                PendingTask.chapter_file == file_path,
                                PendingTask.status == 'published'
                            ).first()

                            if success_task:
                                publish_status = 'published'
                            else:
                                # 查询是否有失败的记录
                                failed_task = db.query(PendingTask).filter(
                                    PendingTask.chapter_file == file_path,
                                    PendingTask.status.in_(['failed', 'cancelled'])
                                ).first()

                                pending_task = db.query(PendingTask).filter(
                                    PendingTask.chapter_file == file_path,
                                    PendingTask.status.in_(['pending', 'publishing'])
                                ).first()

                                if pending_task:
                                    publish_status = 'pending'
                                elif failed_task:
                                    publish_status = 'failed'

                            chapters.append({
                                "file_name": txt_file,
                                "chapter_number": chapter_number,
                                "chapter_title": chapter_title,
                                "word_count": word_count,
                                "file_path": file_path,
                                "publish_status": publish_status
                            })
                        except Exception as e:
                            logger.warning(f"读取文件失败 {file_path}: {e}")

                    # 按章节号排序
                    chapters.sort(key=lambda x: x['chapter_number'])

                except Exception as e:
                    logger.error(f"扫描文件夹失败 {folder}: {e}")

                result.append({
                    "id": book.id,
                    "book_name": book.book_name,
                    "local_folder": folder,
                    "account_name": book.account.name if book.account else None,
                    "exists": True,
                    "chapters": chapters,
                    "total_chapters": len(chapters),
                    "total_words": total_words
                })

            return jsonify(result)
        except Exception as e:
            logger.error(f"获取本地书籍失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()
