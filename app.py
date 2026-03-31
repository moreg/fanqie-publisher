#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
番茄小说自动发布器 - Web服务端
"""
import os
import sys

# 确保项目根目录在Python路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, jsonify, request
from database.connection import init_db, get_session
from database.models import Account, Book, Chapter, Schedule, PublishLog, PendingTask, FeishuConfig
from utils.logger import logger
from config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG


def create_app():
    """创建Flask应用"""
    app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fanqie-secret-key')

    # 注册蓝图
    from web.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    # 初始化数据库
    with app.app_context():
        init_db()

    return app


# 创建应用实例
app = create_app()


@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/api/health')
def health():
    """健康检查"""
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    logger.info(f"启动Web服务: http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
