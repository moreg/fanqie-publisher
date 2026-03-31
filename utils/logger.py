import logging
import sys
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler

from config import BASE_DIR, DATA_DIR


def setup_logger(name="fanqie_publisher"):
    """配置日志"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_fmt)

    # 文件输出 - 使用轮转日志
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 日志轮转配置：每个文件最大10MB，保留5个备份
    max_bytes = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))  # 10MB
    backup_count = int(os.environ.get("LOG_BACKUP_COUNT", 5))

    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        encoding="utf-8",
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_fmt)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


logger = setup_logger()
