import os
import secrets
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
ERRORS_DIR = DATA_DIR / "errors"
NOVELS_DIR = BASE_DIR / "novels"

SECRET_KEY_FILE = DATA_DIR / ".secret_key"

DATABASE_URL = f"sqlite:///{DATA_DIR / 'fanqie.db'}"

FLASK_HOST = "0.0.0.0"
FLASK_PORT = int(os.environ.get("FLASK_PORT", 5000))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"


def get_or_create_secret_key() -> str:
    """获取或创建 SECRET_KEY，持久化到文件"""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    if SECRET_KEY_FILE.exists():
        try:
            with open(SECRET_KEY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                key = data.get("secret_key")
                if key and len(key) >= 32:
                    return key
        except (json.JSONDecodeError, IOError):
            pass

    new_key = secrets.token_hex(32)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(SECRET_KEY_FILE, "w", encoding="utf-8") as f:
            json.dump({"secret_key": new_key}, f)
        print(f"[INFO] 已生成并保存 SECRET_KEY 到 {SECRET_KEY_FILE}")
    except IOError as e:
        print(f"[WARNING] 无法保存 SECRET_KEY 文件: {e}")

    return new_key


SECRET_KEY = get_or_create_secret_key()

# Playwright
BROWSER_HEADLESS = False  # 调试时改为False可以看到浏览器
PAGE_LOAD_TIMEOUT = 30000  # 毫秒
ACTION_TIMEOUT = 15000  # 毫秒

# 发布配置
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 30  # 秒
# 章节发布间隔（秒），发布多个章节时每章之间等待时间，避免被检测为接口发布
PUBLISH_DELAY_BETWEEN_CHAPTERS = int(os.environ.get("PUBLISH_INTERVAL", 60))
# 章节发布前/后的固定等待时间（秒）
PUBLISH_DELAY_MIN = 60   # 发布间隔最小值
PUBLISH_DELAY_MAX = 120  # 发布间隔最大值
MIN_CHAPTER_WORD_COUNT = 1000  # 最小字数
MAX_CHAPTER_WORD_COUNT = 50000  # 最大字数
# 单次「手动发布」API 允许的最大章节数
MAX_MANUAL_PUBLISH_CHAPTERS_PER_REQUEST = int(os.environ.get("MAX_MANUAL_PUBLISH_CHAPTERS", "50"))

# Playwright 异步任务在 HTTP 线程中等待结果的最长时间（秒），需覆盖多章发布与网络延迟
ASYNC_BROWSER_TASK_TIMEOUT = int(os.environ.get("ASYNC_BROWSER_TASK_TIMEOUT", "3600"))

# Session检查
SESSION_CHECK_INTERVAL = 1800  # 秒（30分钟）

# 番茄小说URL
FANQIE_BASE_URL = "https://fanqienovel.com"
FANQIE_LOGIN_URL = f"{FANQIE_BASE_URL}/writer"
FANQIE_BOOK_MANAGE_URL = f"{FANQIE_BASE_URL}/main/writer/book-manage"

# 默认章节文件名正则
DEFAULT_CHAPTER_PATTERN = r"第(\d+)章\s+(.+)\.txt"

# 确保数据目录存在
for d in [DATA_DIR, SESSIONS_DIR, ERRORS_DIR, NOVELS_DIR]:
    d.mkdir(parents=True, exist_ok=True)
