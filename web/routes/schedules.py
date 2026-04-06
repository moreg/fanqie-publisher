"""
调度API
"""
import os
from flask import jsonify, request
from database.connection import get_session
from database.models import Schedule, Chapter, Book, PendingTask
from utils.logger import logger
from datetime import datetime, timedelta


def calculate_next_run(cron_expression: str) -> str:
    """根据 cron 表达式计算下次执行时间，返回格式化字符串"""
    import calendar

    parts = cron_expression.strip().split()
    if len(parts) != 5:
        return None

    minute, hour, day, month, day_of_week = parts

    now = datetime.now()

    # 解析 hour（可能是 "8,20" 或单个数字）
    hours = []
    if ',' in hour:
        hours = [int(h) for h in hour.split(',')]
    else:
        hours = [int(hour)]

    # 解析 day_of_week（可能是 "1-5", "0,6", 单个数字等）
    target_weekdays = set()
    if day_of_week == '1-5':
        target_weekdays = {1, 2, 3, 4, 5}
    elif day_of_week == '0,6':
        target_weekdays = {0, 6}
    elif ',' in day_of_week:
        target_weekdays = {int(d) for d in day_of_week.split(',')}
    elif day_of_week.isdigit():
        target_weekdays = {int(day_of_week)}
    else:
        # 每天
        target_weekdays = None

    # 解析分钟
    minutes = []
    if ',' in minute:
        minutes = [int(m) for m in minute.split(',')]
    else:
        minutes = [int(minute)]

    # 计算下次执行时间
    for days_ahead in range(366):
        check_date = datetime(now.year, now.month, now.day) + timedelta(days=days_ahead)

        # 检查是否是目标星期几
        weekday = check_date.weekday()  # 0=周一, 6=周日
        if target_weekdays is not None and weekday not in target_weekdays:
            continue

        for h in hours:
            for m in minutes:
                check_time = datetime(check_date.year, check_date.month, check_date.day, h, m)
                if check_time > now:
                    # 返回格式化的时间字符串 YYYY-MM-DD HH:mm:ss
                    return check_time.strftime('%Y-%m-%d %H:%M:%S')

    return None


def register_routes(api_bp):
    """注册路由"""

    @api_bp.route('/schedules', methods=['GET'])
    def get_schedules():
        """获取调度列表"""
        db = get_session()
        try:
            schedules = db.query(Schedule).all()
            result = []
            for s in schedules:
                schedule_dict = s.to_dict()
                # 格式化 next_run 为本地时间字符串
                if schedule_dict.get('next_run'):
                    if isinstance(schedule_dict['next_run'], str):
                        # 如果是字符串，解析后重新格式化为本地时间
                        try:
                            dt = datetime.fromisoformat(schedule_dict['next_run'].replace('Z', '+00:00'))
                            schedule_dict['next_run'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            pass
                    elif hasattr(schedule_dict['next_run'], 'strftime'):
                        schedule_dict['next_run'] = schedule_dict['next_run'].strftime('%Y-%m-%d %H:%M:%S')
                # 如果 next_run 为空且任务是启用的，重新计算
                if not schedule_dict.get('next_run') and s.is_active:
                    next_run = calculate_next_run(s.cron_expression)
                    schedule_dict['next_run'] = next_run
                    # 同时更新数据库
                    s.next_run = datetime.strptime(next_run, '%Y-%m-%d %H:%M:%S') if next_run else None
                # 格式化 last_run
                if schedule_dict.get('last_run'):
                    if hasattr(schedule_dict['last_run'], 'strftime'):
                        schedule_dict['last_run'] = schedule_dict['last_run'].strftime('%Y-%m-%d %H:%M:%S')
                result.append(schedule_dict)
            db.commit()
            return jsonify(result)
        finally:
            db.close()

    @api_bp.route('/schedules/preview', methods=['POST'])
    def preview_schedule():
        """预览将发布的章节"""
        import re
        data = request.json
        book_id = data.get('book_id')
        publish_mode = data.get('publish_mode', 'chapters')  # chapters 或 words
        target_value = data.get('target_value', 1)
        start_chapter = data.get('start_chapter', 1)  # 起始章节

        if not book_id:
            return jsonify({"error": "请选择书籍"}), 400
        if target_value <= 0:
            return jsonify({"error": "发布数量必须大于0"}), 400

        db = get_session()
        try:
            # 获取书籍信息
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                return jsonify({"error": "书籍不存在"}), 404

            # 从本地文件夹读取章节
            folder = book.local_folder
            if not folder or not os.path.exists(folder):
                return jsonify({
                    "preview_chapters": [],
                    "total_chapters": 0,
                    "total_words": 0,
                    "message": "本地文件夹不存在"
                })

            # 扫描文件夹中的 txt 文件
            chapters = []
            try:
                files = os.listdir(folder)
                txt_files = [f for f in files if f.endswith('.txt')]

                for txt_file in txt_files:
                    file_path = os.path.join(folder, txt_file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            word_count = len(content)

                        # 解析章节名
                        match = re.search(r'第(\d+)章\s+(.+)', txt_file)
                        if match:
                            chapter_number = int(match.group(1))
                            chapter_title = match.group(2).replace('.txt', '')
                        else:
                            chapter_number = len(chapters) + 1
                            chapter_title = txt_file.replace('.txt', '')

                        # 查询发布状态（同时检查 Chapter 表和 PendingTask 表）
                        publish_status = 'none'

                        # 1. 先检查 Chapter 表的发布状态
                        chapter = db.query(Chapter).filter(
                            Chapter.book_id == book_id,
                            Chapter.chapter_number == chapter_number
                        ).first()
                        if chapter and chapter.status == 'published':
                            publish_status = 'published'

                        # 2. 也检查 PendingTask 表
                        if publish_status != 'published':
                            success_task = db.query(PendingTask).filter(
                                PendingTask.book_id == book_id,
                                PendingTask.chapter_id == chapter.id if chapter else None,
                                PendingTask.status == 'published'
                            ).first()
                            if success_task:
                                publish_status = 'published'

                        chapters.append({
                            "id": chapter_number,
                            "chapter_number": chapter_number,
                            "chapter_title": chapter_title,
                            "word_count": word_count,
                            "file_path": file_path,
                            "publish_status": publish_status
                        })
                    except Exception as e:
                        logger.warning(f"读取文件失败 {file_path}: {e}")
            except Exception as e:
                logger.error(f"扫描文件夹失败 {folder}: {e}")
                return jsonify({
                    "preview_chapters": [],
                    "total_chapters": 0,
                    "total_words": 0,
                    "message": f"扫描文件夹失败: {e}"
                })

            # 按章节号排序
            chapters.sort(key=lambda x: x['chapter_number'])

            # 过滤已发布的章节，并且章节号 >= start_chapter
            pending_chapters = [
                ch for ch in chapters
                if ch['publish_status'] != 'published' and ch['chapter_number'] >= start_chapter
            ]

            if not pending_chapters:
                return jsonify({
                    "preview_chapters": [],
                    "total_chapters": 0,
                    "total_words": 0,
                    "message": "所有章节已发布完成"
                })

            preview_chapters = []
            total_words = 0

            if publish_mode == 'chapters':
                # 按章节数模式：直接取前 N 章
                for i, chapter in enumerate(pending_chapters[:target_value]):
                    preview_chapters.append(chapter)
                    total_words += chapter['word_count']
            else:
                # 按字数模式：累加直到达到目标字数
                accumulated_words = 0
                for chapter in pending_chapters:
                    if accumulated_words >= target_value:
                        break
                    preview_chapters.append(chapter)
                    accumulated_words += chapter['word_count']
                    total_words += chapter['word_count']

            return jsonify({
                "preview_chapters": preview_chapters,
                "total_chapters": len(preview_chapters),
                "total_words": total_words,
                "message": f"将发布 {len(preview_chapters)} 章，共 {total_words} 字"
            })
        except Exception as e:
            logger.error(f"预览失败: {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()

    @api_bp.route('/schedules', methods=['POST'])
    def create_schedule():
        """创建调度"""
        data = request.json
        db = get_session()
        try:
            # 验证书籍存在
            book_id = data.get('book_id')
            if not book_id:
                return jsonify({"error": "请选择书籍"}), 400

            cron_expression = data.get('cron_expression', '0 8 * * *')
            next_run_str = calculate_next_run(cron_expression)
            next_run_dt = datetime.strptime(next_run_str, '%Y-%m-%d %H:%M:%S') if next_run_str else None

            schedule = Schedule(
                book_id=book_id,
                cron_expression=cron_expression,
                publish_mode=data.get('publish_mode', 'chapters'),
                target_value=data.get('target_value', 1),
                start_chapter=data.get('start_chapter', 1),
                is_active=True,
                next_run=next_run_dt
            )
            db.add(schedule)
            db.commit()

            # 更新调度器
            from scheduler.engine import add_publish_job
            add_publish_job(schedule.id, schedule.cron_expression)

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
                # 重新计算下次执行时间
                next_run_str = calculate_next_run(schedule.cron_expression)
                schedule.next_run = datetime.strptime(next_run_str, '%Y-%m-%d %H:%M:%S') if next_run_str else None
            if 'publish_mode' in data:
                schedule.publish_mode = data['publish_mode']
            if 'target_value' in data:
                schedule.target_value = data['target_value']
            if 'start_chapter' in data:
                schedule.start_chapter = data['start_chapter']

            db.commit()

            # 更新调度器
            from scheduler.engine import add_publish_job, remove_publish_job
            if schedule.is_active:
                add_publish_job(schedule.id, schedule.cron_expression)
            else:
                remove_publish_job(schedule.id)

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
                # 从调度器移除
                from scheduler.engine import remove_publish_job
                remove_publish_job(schedule_id)

                db.delete(schedule)
                db.commit()
                return jsonify({"success": True})
            return jsonify({"error": "调度不存在"}), 404
        except Exception as e:
            db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.close()
