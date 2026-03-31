from datetime import datetime

from database.connection import get_session
from database.models import Schedule
from scheduler.engine import add_publish_job
from utils.logger import logger


def recover_missed_schedules():
    """
    应用启动时恢复所有活跃的定时任务
    """
    db = get_session()
    try:
        schedules = db.query(Schedule).filter_by(is_active=True).all()
        for schedule in schedules:
            try:
                add_publish_job(schedule.id, schedule.cron_expression)
                logger.info(f"已恢复定时任务 #{schedule.id} (书籍: {schedule.book.book_name})")
            except Exception as e:
                logger.error(f"恢复定时任务 #{schedule.id} 失败: {e}")
        logger.info(f"共恢复 {len(schedules)} 个定时任务")
    except Exception as e:
        logger.error(f"恢复定时任务失败: {e}")
    finally:
        db.close()
