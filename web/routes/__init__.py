"""
API路由
"""
from flask import Blueprint

api_bp = Blueprint('api', __name__)

from web.routes import accounts, books, chapters, schedules, logs, tasks, feishu

# 注册所有路由
accounts.register_routes(api_bp)
books.register_routes(api_bp)
chapters.register_routes(api_bp)
schedules.register_routes(api_bp)
logs.register_routes(api_bp)
tasks.register_routes(api_bp)
feishu.register_routes(api_bp)
