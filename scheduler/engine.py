import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.logger import logger

# 全局调度器
scheduler = BackgroundScheduler(
    job_defaults={
        "coalesce": True,  # 合并错过的任务
        "max_instances": 1,  # 同一任务最多1个实例
        "misfire_grace_time": 3600,  # 错过1小时内仍执行
    }
)


def init_scheduler():
    """初始化调度器"""
    if not scheduler.running:
        scheduler.start()
        logger.info("调度器已启动")


def shutdown_scheduler():
    """关闭调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("调度器已关闭")


def add_publish_job(schedule_id: int, cron_expression: str):
    """
    添加发布定时任务

    Args:
        schedule_id: 定时任务ID
        cron_expression: Cron表达式，如 "0 8,20 * * *"
    """
    from scheduler.jobs import publish_chapter_job

    job_id = f"publish_{schedule_id}"

    # 解析cron表达式
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        logger.error(f"无效的cron表达式: {cron_expression}")
        return

    minute, hour, day, month, day_of_week = parts

    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )

    # 如果已存在同ID任务，先移除
    remove_publish_job(schedule_id)

    scheduler.add_job(
        publish_chapter_job,
        trigger=trigger,
        args=[schedule_id],
        id=job_id,
        name=f"发布任务 #{schedule_id}",
        replace_existing=True,
    )
    logger.info(f"已添加定时任务 #{schedule_id}: {cron_expression}")


def remove_publish_job(schedule_id: int):
    """移除发布定时任务"""
    job_id = f"publish_{schedule_id}"
    try:
        scheduler.remove_job(job_id)
        logger.info(f"已移除定时任务 #{schedule_id}")
    except Exception:
        pass  # 任务不存在，忽略


def add_session_check_job():
    """添加Session健康检查定时任务（每30分钟）"""
    from scheduler.jobs import check_sessions_job
    from config import SESSION_CHECK_INTERVAL

    interval_minutes = SESSION_CHECK_INTERVAL // 60

    scheduler.add_job(
        check_sessions_job,
        "interval",
        minutes=interval_minutes,
        id="session_check",
        name="Session健康检查",
        replace_existing=True,
    )
    logger.info(f"已添加Session健康检查任务（每 {interval_minutes} 分钟）")


def add_cleanup_job():
    """添加超时章节清理定时任务（每10分钟）"""
    from scheduler.jobs import cleanup_stale_chapters_job

    scheduler.add_job(
        cleanup_stale_chapters_job,
        "interval",
        minutes=10,
        id="chapter_cleanup",
        name="超时章节清理",
        replace_existing=True,
    )
    logger.info("已添加超时章节清理任务（每10分钟）")


def get_job_next_run(schedule_id: int) -> datetime:
    """获取任务的下次运行时间"""
    job_id = f"publish_{schedule_id}"
    job = scheduler.get_job(job_id)
    if job and job.next_run_time:
        return job.next_run_time
    return None
