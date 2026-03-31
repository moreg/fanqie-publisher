"""
调度API
"""
from flask import jsonify, request
from database.connection import get_session
from database.models import Schedule, Chapter
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

    @api_bp.route('/schedules/preview', methods=['POST'])
    def preview_schedule():
        """预览将发布的章节"""
        data = request.json
        book_id = data.get('book_id')
        publish_mode = data.get('publish_mode', 'chapters')  # chapters 或 words
        target_value = data.get('target_value', 1)

        if not book_id:
            return jsonify({"error": "请选择书籍"}), 400
        if target_value <= 0:
            return jsonify({"error": "发布数量必须大于0"}), 400

        db = get_session()
        try:
            # 获取该书籍未发布的章节（按章节号排序）
            chapters = db.query(Chapter).filter(
                Chapter.book_id == book_id,
                Chapter.status == 'pending'
            ).order_by(Chapter.chapter_number).all()

            if not chapters:
                return jsonify({
                    "preview_chapters": [],
                    "total_chapters": 0,
                    "total_words": 0,
                    "message": "该书籍暂无待发布的章节"
                })

            preview_chapters = []
            total_words = 0

            if publish_mode == 'chapters':
                # 按章节数模式：直接取前 N 章
                for i, chapter in enumerate(chapters[:target_value]):
                    preview_chapters.append(chapter.to_dict())
                    total_words += chapter.word_count or 0
            else:
                # 按字数模式：累加直到达到目标字数
                accumulated_words = 0
                for chapter in chapters:
                    if accumulated_words >= target_value:
                        break
                    preview_chapters.append(chapter.to_dict())
                    accumulated_words += chapter.word_count or 0
                    total_words += chapter.word_count or 0

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

            schedule = Schedule(
                book_id=book_id,
                cron_expression=data.get('cron_expression', '0 8,20 * * *'),
                publish_mode=data.get('publish_mode', 'chapters'),
                target_value=data.get('target_value', 1)
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
            if 'publish_mode' in data:
                schedule.publish_mode = data['publish_mode']
            if 'target_value' in data:
                schedule.target_value = data['target_value']

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
