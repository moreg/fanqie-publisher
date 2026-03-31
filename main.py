#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
番茄小说自动发布器 - 统一入口
支持桌面版和Web版启动
"""
import os
import sys
import argparse

# 确保项目根目录在Python路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_desktop():
    """运行桌面版"""
    from gui import main
    main()


def run_web():
    """运行Web版"""
    from app import app
    from config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG
    from utils.logger import logger

    logger.info(f"启动Web服务: http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="番茄小说自动发布器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
运行模式:
  desktop  启动桌面版界面 (默认)
  web      启动Web服务

示例:
  python main.py              # 启动桌面版
  python main.py desktop       # 启动桌面版
  python main.py web          # 启动Web服务
  python main.py web --debug  # 启动Web服务(调试模式)
        """
    )

    parser.add_argument(
        'mode',
        nargs='?',
        choices=['desktop', 'web'],
        default='desktop',
        help='运行模式: desktop(桌面版) 或 web(Web服务) (默认: desktop)'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='启用调试模式 (仅Web模式)'
    )

    parser.add_argument(
        '--host',
        default=None,
        help='Web服务监听地址 (默认: 0.0.0.0)'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='Web服务监听端口 (默认: 5000)'
    )

    args = parser.parse_args()

    # 设置调试模式
    if args.debug:
        os.environ['FLASK_DEBUG'] = 'true'

    if args.host:
        os.environ['FLASK_HOST'] = args.host

    if args.port:
        os.environ['FLASK_PORT'] = str(args.port)

    # 根据模式启动
    if args.mode == 'web':
        run_web()
    else:
        run_desktop()


if __name__ == '__main__':
    main()
