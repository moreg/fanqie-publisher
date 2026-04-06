"""
书籍API
"""
import os
import re
import shutil
from datetime import datetime
from flask import jsonify, request
from database.connection import get_session
from database.models import Book, Chapter, Account, PendingTask, PublishLog
from utils.logger import logger


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/books/import', methods=['POST'])
    def import_novel():
        """导入小说文件（txt格式），自动拆分成章节"""
        data = request.json
        book_name = data.get('book_name', '')
        account_id = data.get('account_id')
        file_content = data.get('content', '')  # 小说文件内容
        base_folder = data.get('base_folder', '')  # 保存的基础文件夹

        if not book_name:
            return jsonify({"error": "书名不能为空"}), 400
        if not account_id:
            return jsonify({"error": "请选择账号"}), 400
        if not file_content:
            return jsonify({"error": "文件内容为空"}), 400

        db = get_session()
        try:
            # 创建书籍文件夹
            book_folder = os.path.join(base_folder, book_name)
            if os.path.exists(book_folder):
                # 文件夹已存在，清理旧文件
                for f in os.listdir(book_folder):
                    os.remove(os.path.join(book_folder, f))
            else:
                os.makedirs(book_folder, exist_ok=True)

            # 解析章节
            chapters = []
            lines = file_content.split('\n')

            # 第一行是书名（如果有的话）
            first_line = lines[0].strip() if lines else ''
            if not book_name and first_line:
                book_name = first_line[:100]  # 截取前100字符作为书名

            # 跳过第一行（书名），处理剩余内容
            content_lines = lines[1:] if lines else []

            # 合并所有内容行
            full_content = '\n'.join(content_lines)

            # 使用正则表达式匹配章节：第X章 或 第X章：标题
            chapter_pattern = re.compile(r'^第(\d+)章[：:]\s*(.+?)$', re.MULTILINE)

            matches = list(chapter_pattern.finditer(full_content))

            if not matches:
                # 没有找到章节格式，将整个内容作为第一章
                chapter_file = os.path.join(book_folder, '第1章 正文.txt')
                with open(chapter_file, 'w', encoding='utf-8') as f:
                    f.write(full_content.strip())
                chapters.append({
                    "chapter_number": 1,
                    "chapter_title": "正文",
                    "file_path": chapter_file
                })
            else:
                # 拆分成多个章节
                for i, match in enumerate(matches):
                    chapter_num = int(match.group(1))
                    chapter_title = match.group(2).strip()

                    # 获取章节内容
                    start_pos = match.end()
                    end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(full_content)
                    chapter_content = full_content[start_pos:end_pos].strip()

                    # 保存章节文件
                    chapter_file = os.path.join(book_folder, f'第{chapter_num}章 {chapter_title}.txt')
                    with open(chapter_file, 'w', encoding='utf-8') as f:
                        f.write(chapter_content)

                    chapters.append({
                        "chapter_number": chapter_num,
                        "chapter_title": chapter_title,
                        "file_path": chapter_file
                    })

            # 创建书籍记录
            book = Book(
                account_id=account_id,
                book_name=book_name,
                local_folder=book_folder,
                chapter_pattern=r"第(\d+)章\s+(.+)\.txt"
            )
            db.add(book)
            db.commit()

            logger.info(f"导入小说《{book_name}》，共 {len(chapters)} 章")

            return jsonify({
                "success": True,
                "book_id": book.id,
                "book_name": book_name,
                "folder": book_folder,
                "chapters_count": len(chapters)
            })

        except Exception as e:
            db.rollback()
            logger.error(f"导入小说失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

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

                    # 构建番茄网站上当前有效的书籍ID集合
                    active_book_ids = {book.get('fanqie_book_id') for book in books_data}

                    # 同步到数据库
                    synced_count = 0
                    deleted_count = 0

                    # 先检查并删除数据库中已完结/隐藏的书籍
                    existing_books = db.query(Book).filter_by(account_id=account_id).all()
                    for existing_book in existing_books:
                        # 如果数据库中的书籍在番茄网站上找不到，说明已完结/隐藏
                        if existing_book.fanqie_book_id not in active_book_ids:
                            book_name = existing_book.book_name
                            # 删除关联的章节
                            from database.models import Chapter
                            db.query(Chapter).filter_by(book_id=existing_book.id).delete()
                            # 删除关联的待发布任务
                            from database.models import PendingTask
                            db.query(PendingTask).filter_by(book_id=existing_book.id).delete()
                            # 删除关联的定时任务
                            from database.models import Schedule
                            db.query(Schedule).filter_by(book_id=existing_book.id).delete()
                            # 删除书籍本身
                            db.delete(existing_book)
                            deleted_count += 1
                            logger.info(f"自动删除已完结/隐藏书籍: {book_name}")

                    # 更新或添加书籍
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
                    logger.info(f"同步完成: 新增 {synced_count} 本, 删除 {deleted_count} 本已完结书籍")
                    return {"success": True, "synced": synced_count, "deleted": deleted_count, "total": len(books_data)}
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
                            # 尝试多种编码读取文件
                            content = None
                            for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']:
                                try:
                                    with open(file_path, 'r', encoding=encoding) as f:
                                        content = f.read()
                                    break
                                except UnicodeDecodeError:
                                    continue

                            if content is None:
                                logger.warning(f"无法识别文件编码: {file_path}")
                                continue

                            word_count = len(content.strip()) if content.strip() else len(content)
                            total_words += word_count

                            # 解析章节名
                            match = re.search(r'第(\d+)章 (.+)', txt_file)
                            if match:
                                chapter_number = int(match.group(1))
                                chapter_title = match.group(2).replace('.txt', '')
                            else:
                                chapter_number = len(chapters) + 1
                                chapter_title = txt_file.replace('.txt', '')

                            # 查询章节发布状态
                            publish_status = 'none'  # none: 未发布, pending: 待发布, published: 已发布, failed: 发布失败
                            chapter_id = None  # 章节ID，用于状态更新

                            # 1. 先检查 Chapter 表的发布状态
                            db_chapter = db.query(Chapter).filter(
                                Chapter.book_id == book.id,
                                Chapter.chapter_number == chapter_number
                            ).first()
                            if db_chapter:
                                chapter_id = db_chapter.id
                                if db_chapter.status == 'published':
                                    publish_status = 'published'
                                elif db_chapter.status == 'pending':
                                    publish_status = 'pending'
                                elif db_chapter.status == 'failed':
                                    publish_status = 'failed'

                            # 2. 如果 Chapter 表没有状态，检查 PendingTask 表
                            if publish_status == 'none':
                                success_task = db.query(PendingTask).filter(
                                    PendingTask.chapter_file == file_path,
                                    PendingTask.status == 'published'
                                ).first()

                                if success_task:
                                    publish_status = 'published'
                                    # 自动创建 Chapter 记录，以便前端可以更新状态
                                    new_chapter = Chapter(
                                        book_id=book.id,
                                        chapter_number=chapter_number,
                                        chapter_title=chapter_title,
                                        file_path=file_path,
                                        word_count=word_count,
                                        status='published',
                                        published_at=success_task.updated_at
                                    )
                                    db.add(new_chapter)
                                    db.flush()  # 刷新以获取ID
                                    chapter_id = new_chapter.id
                                    db.commit()
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
                                        # 自动创建 Chapter 记录
                                        new_chapter = Chapter(
                                            book_id=book.id,
                                            chapter_number=chapter_number,
                                            chapter_title=chapter_title,
                                            file_path=file_path,
                                            word_count=word_count,
                                            status='pending'
                                        )
                                        db.add(new_chapter)
                                        db.flush()  # 刷新以获取ID
                                        chapter_id = new_chapter.id
                                        db.commit()
                                    elif failed_task:
                                        publish_status = 'failed'
                                        # 自动创建 Chapter 记录
                                        new_chapter = Chapter(
                                            book_id=book.id,
                                            chapter_number=chapter_number,
                                            chapter_title=chapter_title,
                                            file_path=file_path,
                                            word_count=word_count,
                                            status='failed'
                                        )
                                        db.add(new_chapter)
                                        db.flush()  # 刷新以获取ID
                                        chapter_id = new_chapter.id
                                        db.commit()

                            chapters.append({
                                "id": chapter_id,
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

    @api_bp.route('/books/<int:book_id>/open-folder', methods=['POST'])
    def open_book_folder(book_id):
        """打开书籍本地文件夹"""
        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                return jsonify({"error": "书籍不存在"}), 404

            folder = book.local_folder
            if not folder or not os.path.exists(folder):
                return jsonify({"error": "文件夹不存在"}), 400

            # 使用 Windows explorer 打开文件夹
            import subprocess
            subprocess.Popen(f'explorer.exe "{folder}"')
            return jsonify({"success": True, "folder": folder})
        except Exception as e:
            logger.error(f"打开文件夹失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/books/quick-publish', methods=['POST'])
    def quick_publish():
        """一键发书：立即将书籍章节添加到待发布队列"""
        data = request.json
        book_id = data.get('book_id')
        chapters_per_run = data.get('chapters_per_run', 2)
        start_chapter = data.get('start_chapter', 1)

        if not book_id:
            return jsonify({"success": False, "message": "请选择书籍"}), 400

        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                return jsonify({"success": False, "message": "书籍不存在"}), 404

            folder = book.local_folder
            if not folder or not os.path.exists(folder):
                return jsonify({"success": False, "message": "书籍文件夹不存在"}), 400

            # 获取已在队列中的章节文件路径（来自PendingTask）
            pending_tasks = db.query(PendingTask).filter_by(book_id=book_id).all()
            pending_files = {task.chapter_file for task in pending_tasks}

            # 获取已发布的章节号（只跳过published状态）
            published_chapters = db.query(Chapter).filter_by(book_id=book_id, status='published').all()
            published_numbers = {ch.chapter_number for ch in published_chapters}

            # 扫描本地文件
            added = 0
            existing = 0
            skipped = 0

            files = os.listdir(folder)
            txt_files = [f for f in files if f.endswith('.txt')]

            for txt_file in txt_files:
                file_path = os.path.join(folder, txt_file)

                # 解析章节号
                match = re.search(r'第([0-9]+)', txt_file)
                if not match:
                    continue
                chapter_num = int(match.group(1))

                # 跳过起始章节之前的
                if chapter_num < start_chapter:
                    skipped += 1
                    continue

                # 跳过已发布的章节
                if chapter_num in published_numbers:
                    skipped += 1
                    continue

                # 跳过文件路径已在PendingTask中的
                if file_path in pending_files:
                    existing += 1
                    continue

                # 解析章节标题
                chapter_match = re.search(r'第([0-9]+)章 (.+)', txt_file)
                if chapter_match:
                    chapter_num = int(chapter_match.group(1))
                    chapter_title = chapter_match.group(2).replace('.txt', '').strip()
                else:
                    chapter_title = txt_file.replace('.txt', '').strip()

                # 添加到待发布队列
                pending_task = PendingTask(
                    book_id=book_id,
                    chapter_file=file_path,
                    chapter_title=chapter_title,
                    scheduled_time=datetime.now()
                )
                db.add(pending_task)
                pending_files.add(file_path)
                added += 1

                # 如果达到每轮发布数量，停止
                if added >= chapters_per_run:
                    break

            db.commit()

            logger.info(f"一键发书《{book.book_name}》：新增 {added} 章，已在队列 {existing} 章，跳过 {skipped} 章")

            return jsonify({
                "success": True,
                "added": added,
                "existing": existing,
                "skipped": skipped,
                "message": f"已添加 {added} 章到待发布队列"
            })

        except Exception as e:
            db.rollback()
            logger.error(f"一键发书失败: {e}")
            return jsonify({"success": False, "message": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/books/<int:book_id>/sync-published', methods=['POST'])
    def sync_published_chapters(book_id):
        """同步番茄小说已发布章节状态到本地"""
        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                return jsonify({"success": False, "message": "书籍不存在"}), 404

            if not book.fanqie_book_id:
                return jsonify({"success": False, "message": "该书籍未绑定番茄小说ID"}), 400

            account = book.account
            if not account:
                return jsonify({"success": False, "message": "书籍没有关联账号"}), 400

            if not account.cookies and not account.session_file:
                return jsonify({"success": False, "message": "账号没有有效的Cookie或Session"}), 400

            # 使用浏览器获取番茄已发布章节
            from browser.manager import browser_manager

            async def _sync():
                from browser.fanqie.chapter_checker import ChapterChecker

                context = await browser_manager._async_create_context_from_session(account.id)
                if context is None:
                    return {"success": False, "message": "无法创建浏览器上下文"}

                page = await context.new_page()
                try:
                    checker = ChapterChecker(page)
                    published_titles = await checker.get_published_chapters(book.fanqie_book_id)

                    if not published_titles:
                        return {"success": False, "message": "未获取到番茄已发布章节，可能Cookie已过期"}

                    # 获取本地章节
                    local_chapters = db.query(Chapter).filter_by(book_id=book_id).all()
                    folder = book.local_folder

                    synced_count = 0
                    if folder and os.path.exists(folder):
                        files = os.listdir(folder)
                        for f in files:
                            if not f.endswith('.txt'):
                                continue

                            file_path = os.path.join(folder, f)
                            match = re.search(r'第(\d+)章 (.+)', f)
                            if not match:
                                continue

                            chapter_title = match.group(2).replace('.txt', '').strip()

                            # 检查是否在番茄已发布列表中
                            for pub_title in published_titles:
                                if _title_match(chapter_title, pub_title):
                                    # 查找或创建本地章节记录
                                    chapter_num = int(match.group(1))
                                    chapter = db.query(Chapter).filter_by(
                                        book_id=book_id,
                                        chapter_number=chapter_num
                                    ).first()

                                    if chapter:
                                        if chapter.status != 'published':
                                            chapter.status = 'published'
                                            chapter.published_at = datetime.now()
                                            synced_count += 1
                                    else:
                                        # 创建新记录
                                        new_chapter = Chapter(
                                            book_id=book_id,
                                            chapter_number=chapter_num,
                                            chapter_title=chapter_title,
                                            file_path=file_path,
                                            status='published',
                                            published_at=datetime.now()
                                        )
                                        db.add(new_chapter)
                                        synced_count += 1
                                    break

                    db.commit()
                    return {
                        "success": True,
                        "synced": synced_count,
                        "published_count": len(published_titles),
                        "message": f"已同步 {synced_count} 个章节为已发布状态"
                    }

                finally:
                    await page.close()
                    await context.close()

            result = browser_manager._run_async(_sync())
            return jsonify(result)

        except Exception as e:
            db.rollback()
            logger.error(f"同步已发布章节失败: {e}")
            return jsonify({"success": False, "message": str(e)}), 500
        finally:
            db.close()


def _title_match(title1: str, title2: str) -> bool:
    """判断两个章节标题是否匹配"""
    if not title1 or not title2:
        return False
    if title1 == title2:
        return True
    # 去除数字后的匹配
    import re
    t1_no_num = re.sub(r'[\d]+', '', title1)
    t2_no_num = re.sub(r'[\d]+', '', title2)
    t1_simple = re.sub(r'[\s\.\-\_～\：\:\、\，]', '', t1_no_num)
    t2_simple = re.sub(r'[\s\.\-\_～\：\:\、\，]', '', t2_no_num)
    if t1_simple == t2_simple:
        return True
    if len(t1_simple) > 3 and len(t2_simple) > 3:
        if t1_simple in t2_simple or t2_simple in t1_simple:
            return True
    return False


