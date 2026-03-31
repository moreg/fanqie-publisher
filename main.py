#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
番茄小说自动发布器 - Web服务端入口
"""
import os
import sys
import argparse

# 确保项目根目录在Python路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description="番茄小说自动发布器 - Web服务")
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000, help='监听端口 (默认: 5000)')

    args = parser.parse_args()

    if args.debug:
        os.environ['FLASK_DEBUG'] = 'true'

    from app import app
    from config import FLASK_DEBUG
    from utils.logger import logger

    host = args.host or '0.0.0.0'
    port = args.port or 5000
    debug = args.debug or FLASK_DEBUG

    logger.info(f"启动Web服务: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
