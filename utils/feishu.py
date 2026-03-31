"""
飞书通知模块
"""
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from utils.logger import logger


@dataclass
class FeishuConfig:
    """飞书配置"""
    app_id: str
    app_secret: str
    webhook_url: str
    enabled: bool = True


class FeishuNotifier:
    """飞书通知器"""

    def __init__(self, config: Optional[FeishuConfig] = None):
        self.config = config

    def set_config(self, config: FeishuConfig):
        """设置配置"""
        self.config = config

    def is_enabled(self) -> bool:
        """检查是否启用"""
        return (
            self.config is not None and
            self.config.enabled and
            bool(self.config.webhook_url)
        )

    def send_publish_success(
        self,
        book_name: str,
        chapter_title: str,
        publish_time: datetime = None
    ) -> bool:
        """发送发布成功通知

        Args:
            book_name: 书名
            chapter_title: 章节名称
            publish_time: 发布时间
        """
        if not self.is_enabled():
            logger.debug("飞书通知未启用，跳过发送")
            return False

        if publish_time is None:
            publish_time = datetime.now()

        content = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "番茄小说发布成功"},
                    "template": "green"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**📖 书名：**\n{book_name}"
                        }
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**📑 章节：**\n{chapter_title}"
                        }
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**✅ 发布状态：**\n成功"
                        }
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**🕐 发布时间：**\n{publish_time.strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    }
                ]
            }
        }

        return self._send(content)

    def send_publish_failed(
        self,
        book_name: str,
        chapter_title: str,
        error_message: str,
        publish_time: datetime = None
    ) -> bool:
        """发送发布失败通知"""
        if not self.is_enabled():
            logger.debug("飞书通知未启用，跳过发送")
            return False

        if publish_time is None:
            publish_time = datetime.now()

        content = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "番茄小说发布失败"},
                    "template": "red"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**📖 书名：**\n{book_name}"
                        }
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**📑 章节：**\n{chapter_title}"
                        }
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**❌ 发布状态：**\n失败"
                        }
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**📝 错误原因：**\n{error_message}"
                        }
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**🕐 操作时间：**\n{publish_time.strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    }
                ]
            }
        }

        return self._send(content)

    def _send(self, content: dict) -> bool:
        """发送消息到飞书"""
        if not self.config or not self.config.webhook_url:
            logger.warning("飞书webhook未配置")
            return False

        try:
            data = json.dumps(content).encode("utf-8")
            req = urllib.request.Request(
                self.config.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"}
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))

            if result.get("code") == 0 or result.get("StatusCode") == 0:
                logger.info("飞书通知发送成功")
                return True
            else:
                logger.error(f"飞书通知发送失败: {result}")
                return False

        except urllib.error.URLError as e:
            logger.error(f"飞书通知发送失败: {e}")
            return False
        except Exception as e:
            logger.error(f"飞书通知发送异常: {e}")
            return False


# 全局单例
feishu_notifier = FeishuNotifier()


def get_feishu_notifier() -> FeishuNotifier:
    """获取飞书通知器实例"""
    return feishu_notifier
