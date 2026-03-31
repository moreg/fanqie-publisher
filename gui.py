#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
番茄小说自动发布器 - Windows桌面版 (现代化UI)
"""
import os
import sys
import threading
from datetime import datetime

# 确保项目根目录在Python路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import customtkinter as ctk
import tkinter.ttk as ttk
from database.connection import get_session, init_db, safe_session
from database.models import Account, Book, Chapter, PendingTask, PublishLog
from scheduler.task_scheduler import task_scheduler
from browser.manager import browser_manager
from utils.logger import logger
from config import PUBLISH_DELAY_BETWEEN_CHAPTERS, PUBLISH_DELAY_MIN, PUBLISH_DELAY_MAX

# ==================== 现代化配色方案 ====================
class Colors:
    """配色方案"""
    # 主色调 - 深邃紫蓝色
    BG_DARK = "#0F0F1A"           # 最深背景
    BG_MAIN = "#1A1A2E"           # 主背景
    BG_CARD = "#252540"           # 卡片背景
    BG_HOVER = "#2D2D4A"          # 悬停背景

    # 渐变色
    GRADIENT_START = "#667EEA"     # 渐变起始色
    GRADIENT_END = "#764BA2"       # 渐变结束色

    # 功能色
    ACCENT_BLUE = "#4F8EF7"        # 主强调色
    ACCENT_GREEN = "#10B981"      # 成功色
    ACCENT_ORANGE = "#F59E0B"     # 警告色
    ACCENT_RED = "#EF4444"        # 错误色
    ACCENT_PURPLE = "#8B5CF6"     # 特殊色

    # 文字色
    TEXT_PRIMARY = "#FFFFFF"
    TEXT_SECONDARY = "#A0A0B0"
    TEXT_MUTED = "#6B7280"

    # 边框色
    BORDER = "#3D3D5C"
    BORDER_LIGHT = "#4D4D6C"


# 设置外观
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def create_button(parent, text, command=None, fg_color=None, hover_color=None,
                  text_color=None, width=130, height=48):
    """创建现代化按钮"""
    if fg_color is None:
        fg_color = Colors.ACCENT_BLUE
    if hover_color is None:
        hover_color = Colors.BG_HOVER
    if text_color is None:
        text_color = Colors.TEXT_PRIMARY

    btn = ctk.CTkButton(
        parent,
        text=text,
        command=command,
        fg_color=fg_color,
        hover_color=hover_color,
        text_color=text_color,
        corner_radius=8,
        height=height,
        width=width,
        font=("Microsoft YaHei UI", 15, "bold"),
        cursor="hand2"
    )
    return btn


class PrimaryButton(ctk.CTkButton):
    """主按钮 - 蓝色"""
    def __init__(self, parent, text, command=None, width=130, height=48, **kwargs):
        super().__init__(
            parent,
            text=text,
            command=command,
            fg_color=Colors.ACCENT_BLUE,
            hover_color="#3A7BE0",
            text_color=Colors.TEXT_PRIMARY,
            corner_radius=8,
            height=height,
            width=width,
            font=("Microsoft YaHei UI", 15, "bold"),
            cursor="hand2",
            **kwargs
        )


class SuccessButton(ctk.CTkButton):
    """成功按钮 - 绿色"""
    def __init__(self, parent, text, command=None, width=130, height=48, **kwargs):
        super().__init__(
            parent,
            text=text,
            command=command,
            fg_color=Colors.ACCENT_GREEN,
            hover_color="#0D9668",
            text_color=Colors.TEXT_PRIMARY,
            corner_radius=8,
            height=height,
            width=width,
            font=("Microsoft YaHei UI", 15, "bold"),
            cursor="hand2",
            **kwargs
        )


class DangerButton(ctk.CTkButton):
    """危险按钮 - 红色"""
    def __init__(self, parent, text, command=None, width=130, height=48, **kwargs):
        super().__init__(
            parent,
            text=text,
            command=command,
            fg_color=Colors.ACCENT_RED,
            hover_color="#DC2626",
            text_color=Colors.TEXT_PRIMARY,
            corner_radius=8,
            height=height,
            width=width,
            font=("Microsoft YaHei UI", 15, "bold"),
            cursor="hand2",
            **kwargs
        )


class GhostButton(ctk.CTkButton):
    """幽灵按钮 - 透明背景"""
    def __init__(self, parent, text, command=None, width=130, height=48, **kwargs):
        super().__init__(
            parent,
            text=text,
            command=command,
            fg_color="transparent",
            hover_color=Colors.BG_HOVER,
            text_color=Colors.TEXT_SECONDARY,
            corner_radius=8,
            height=height,
            width=width,
            border_width=1,
            border_color=Colors.BORDER,
            font=("Microsoft YaHei UI", 15),
            cursor="hand2",
            **kwargs
        )


class ModernCard(ctk.CTkFrame):
    """现代化卡片组件"""

    def __init__(self, parent, title=None, **kwargs):
        super().__init__(
            parent,
            fg_color=Colors.BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=Colors.BORDER,
            **kwargs
        )

        if title:
            self._create_header(title)

    def _create_header(self, title):
        """创建卡片头部"""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))

        title_label = ctk.CTkLabel(
            header,
            text=title,
            font=("Microsoft YaHei UI", 16, "bold"),
            text_color=Colors.TEXT_PRIMARY
        )
        title_label.pack(side="left")


class TreeviewFrame(ctk.CTkFrame):
    """表格框架 - 现代化样式"""

    def __init__(self, parent, columns, headings, widths, **kwargs):
        super().__init__(
            parent,
            fg_color="transparent",
            corner_radius=0,
            **kwargs
        )

        # 创建Treeview
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="headings",
            height=12,
            style="Modern.Treeview"
        )

        # 设置列
        for col, heading, width in zip(columns, headings, widths):
            self.tree.heading(col, text=heading, anchor="center")
            self.tree.column(col, width=width, anchor="w", minwidth=50)

        # 滚动条
        vsb = ctk.CTkScrollbar(self, orientation="vertical", command=self.tree.yview, fg_color=Colors.BG_CARD)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=0)
        vsb.pack(side="right", fill="y")

        # 设置样式
        self._apply_style()

    def _apply_style(self):
        """应用现代化样式"""
        style = ttk.Style()
        style.theme_use("clam")

        # 表格样式
        style.configure("Modern.Treeview",
            background=Colors.BG_CARD,
            foreground=Colors.TEXT_PRIMARY,
            fieldbackground=Colors.BG_CARD,
            rowheight=48,
            borderwidth=0,
            font=("Microsoft YaHei UI", 16)
        )

        # 表头样式
        style.configure("Modern.Treeview.Heading",
            background=Colors.BG_MAIN,
            foreground=Colors.TEXT_SECONDARY,
            borderwidth=0,
            font=("Microsoft YaHei UI", 16, "bold")
        )

        # 悬停效果
        style.map("Modern.Treeview",
            background=[("selected", Colors.BG_HOVER)],
            foreground=[("selected", Colors.TEXT_PRIMARY)]
        )

    def insert(self, values):
        """插入行"""
        self.tree.insert("", "end", values=values, tags=("row",))

    def clear(self):
        """清空"""
        for item in self.tree.get_children():
            self.tree.delete(item)

    def get_selection(self):
        """获取选中项"""
        selection = self.tree.selection()
        if selection:
            values = self.tree.item(selection[0])["values"]
            return values[0] if values else None
        return None

    def get_all_selections(self):
        """获取所有选中项的第一列值"""
        return [self.tree.item(item)["values"][0] for item in self.tree.selection()]


class ModernEntry(ctk.CTkEntry):
    """现代化输入框"""

    def __init__(self, parent, placeholder=None, **kwargs):
        super().__init__(
            parent,
            placeholder_text=placeholder,
            fg_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            border_width=1,
            corner_radius=8,
            height=48,
            font=("Microsoft YaHei UI", 15),
            text_color=Colors.TEXT_PRIMARY,
            placeholder_text_color=Colors.TEXT_MUTED,
            **kwargs
        )


class ModernSwitch(ctk.CTkSwitch):
    """现代化开关"""

    def __init__(self, parent, text="", **kwargs):
        super().__init__(
            parent,
            text=text,
            on_color=Colors.ACCENT_GREEN,
            off_color=Colors.BORDER,
            progress_color=Colors.ACCENT_BLUE,
            button_color=Colors.TEXT_PRIMARY,
            corner_radius=12,
            height=36,
            font=("Microsoft YaHei UI", 14),
            text_color=Colors.TEXT_SECONDARY,
            **kwargs
        )


class ModernComboBox(ctk.CTkComboBox):
    """现代化下拉框"""

    def __init__(self, parent, values=None, **kwargs):
        super().__init__(
            parent,
            values=values or [],
            fg_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            button_color=Colors.ACCENT_BLUE,
            dropdown_fg_color=Colors.BG_CARD,
            dropdown_hover_color=Colors.BG_HOVER,
            corner_radius=8,
            height=48,
            font=("Microsoft YaHei UI", 15),
            text_color=Colors.TEXT_PRIMARY,
            **kwargs
        )


class StatusBadge(ctk.CTkLabel):
    """状态徽章"""

    COLORS = {
        "pending": (Colors.ACCENT_ORANGE, "#000000"),
        "publishing": (Colors.ACCENT_BLUE, Colors.TEXT_PRIMARY),
        "published": (Colors.ACCENT_GREEN, Colors.TEXT_PRIMARY),
        "failed": (Colors.ACCENT_RED, Colors.TEXT_PRIMARY),
        "active": (Colors.ACCENT_GREEN, Colors.TEXT_PRIMARY),
        "inactive": (Colors.TEXT_MUTED, Colors.TEXT_PRIMARY),
        "success": (Colors.ACCENT_GREEN, Colors.TEXT_PRIMARY),
    }

    def __init__(self, parent, text, status_type="pending", **kwargs):
        color_pair = self.COLORS.get(status_type, (Colors.TEXT_MUTED, Colors.TEXT_PRIMARY))
        super().__init__(
            parent,
            text=text,
            fg_color=color_pair[0],
            text_color=color_pair[1],
            corner_radius=10,
            padding=(14, 6),
            font=("Microsoft YaHei UI", 13, "bold"),
            **kwargs
        )


class ModernDialog(ctk.CTkToplevel):
    """现代化对话框"""

    def __init__(self, parent, title, width=450, height=350):
        super().__init__(parent)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=Colors.BG_MAIN)

        # 居中显示
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

        # 内容框架
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True, padx=30, pady=20)


class FanqieApp(ctk.CTk):
    """番茄小说自动发布器 - 现代化UI"""

    def __init__(self):
        super().__init__()

        # 窗口配置
        self.title("番茄小说自动发布器")
        self.geometry("1400x800")
        self.minsize(1200, 700)
        self.configure(fg_color=Colors.BG_DARK)

        # 初始化
        self._init_system()
        self._setup_ui()
        self._start_scheduler()
        self._refresh_all()

        # 定时刷新
        self._start_auto_refresh()

        # 关闭处理
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_system(self):
        """初始化系统"""
        logger.info("初始化数据库...")
        init_db()

    def _setup_ui(self):
        """设置界面"""
        # 主容器
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # 顶部标题栏
        self._create_header()

        # 左侧导航
        self._create_sidebar()

        # 主内容区
        self.content_frame = ctk.CTkFrame(self, fg_color=Colors.BG_MAIN, corner_radius=0)
        self.content_frame.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.content_frame.grid_rowconfigure(1, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        # 默认显示任务页面
        self.current_view = None
        self._show_tasks()

    def _create_header(self):
        """创建顶部标题栏"""
        header = ctk.CTkFrame(self, height=60, fg_color=Colors.BG_MAIN, corner_radius=0)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        # 左侧标题
        title_label = ctk.CTkLabel(
            header,
            text="番茄小说自动发布器",
            font=("Microsoft YaHei UI", 20, "bold"),
            text_color=Colors.TEXT_PRIMARY
        )
        title_label.grid(row=0, column=0, padx=24, pady=0, sticky="w")

        # 副标题
        subtitle = ctk.CTkLabel(
            header,
            text="FanQie Novel Publisher",
            font=("Segoe UI", 10),
            text_color=Colors.TEXT_MUTED
        )
        subtitle.grid(row=1, column=0, padx=24, pady=(0, 0), sticky="w")

        # 右侧状态
        self.header_status = ctk.CTkLabel(
            header,
            text="系统就绪",
            font=("Microsoft YaHei UI", 12),
            text_color=Colors.ACCENT_GREEN
        )
        self.header_status.grid(row=0, column=1, padx=20, sticky="e")

        # 分隔线
        separator = ctk.CTkFrame(header, height=1, fg_color=Colors.BORDER)
        separator.grid(row=2, column=0, columnspan=2, sticky="ew")

    def _create_sidebar(self):
        """创建侧边栏导航"""
        sidebar = ctk.CTkFrame(self, width=220, fg_color=Colors.BG_DARK, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(8, weight=1)

        # 导航项目
        nav_items = [
            ("tasks", "📋", "待发布任务", self._show_tasks),
            ("books", "📚", "书籍管理", self._show_books),
            ("chapters", "📖", "章节列表", self._show_chapters),
            ("accounts", "👤", "账号管理", self._show_accounts),
            ("logs", "📊", "发布日志", self._show_logs),
            ("feishu", "🔔", "飞书配置", self._show_feishu_config),
        ]

        self.nav_buttons = {}
        for i, (item_id, icon, text, cmd) in enumerate(nav_items, 1):
            btn = self._create_nav_button(sidebar, icon, text, cmd)
            btn.grid(row=i, column=0, padx=12, pady=4, sticky="ew")
            self.nav_buttons[item_id] = btn

        # 底部信息
        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=9, column=0, padx=12, pady=10, sticky="ew")

        version_label = ctk.CTkLabel(
            footer,
            text="v1.0.0",
            font=("Microsoft YaHei UI", 10),
            text_color=Colors.TEXT_MUTED
        )
        version_label.pack()

    def _create_nav_button(self, parent, icon, text, command):
        """创建导航按钮"""
        btn = ctk.CTkButton(
            parent,
            text=f"  {icon}  {text}",
            command=command,
            fg_color="transparent",
            hover_color=Colors.BG_HOVER,
            text_color=Colors.TEXT_SECONDARY,
            anchor="w",
            height=48,
            corner_radius=10,
            font=("Microsoft YaHei UI", 14)
        )
        return btn

    def _set_active_nav(self, item_id):
        """设置激活的导航"""
        for nav_id, btn in self.nav_buttons.items():
            if nav_id == item_id:
                btn.configure(fg_color=Colors.ACCENT_BLUE, text_color=Colors.TEXT_PRIMARY)
            else:
                btn.configure(fg_color="transparent", text_color=Colors.TEXT_SECONDARY)

    # ==================== 页面视图 ====================

    def _show_tasks(self):
        """显示待发布任务页面"""
        self._clear_content()
        self.current_view = "tasks"
        self._set_active_nav("tasks")

        # 页面标题
        self._create_page_header("📋 待发布任务", "管理定时发布任务")

        # 操作按钮栏
        btn_bar = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        btn_bar.pack(fill="x", padx=24, pady=(16, 12))

        PrimaryButton(btn_bar, "➕ 添加任务", command=self._show_add_task_dialog, width=130).pack(side="left", padx=4)
        GhostButton(btn_bar, "🔄 刷新", command=self._refresh_tasks, width=100).pack(side="left", padx=4)
        DangerButton(btn_bar, "🗑️ 删除选中", command=self._delete_selected_tasks, width=120).pack(side="left", padx=4)

        # 表格
        table_frame = ctk.CTkFrame(self.content_frame, fg_color=Colors.BG_CARD, corner_radius=12)
        table_frame.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        columns = ("id", "account", "book", "chapter", "scheduled", "status")
        headings = ("ID", "账号", "小说名", "章节标题", "计划发布时间", "状态")
        widths = (60, 100, 160, 280, 160, 100)
        self.tasks_tree = TreeviewFrame(table_frame, columns, headings, widths)
        self.tasks_tree.pack(fill="both", expand=True, padx=12, pady=12)

        self._refresh_tasks()

    def _show_books(self):
        """显示书籍管理页面"""
        self._clear_content()
        self.current_view = "books"
        self._set_active_nav("books")

        self._create_page_header("📚 书籍管理", "管理番茄小说书籍")

        btn_bar = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        btn_bar.pack(fill="x", padx=24, pady=(16, 12))

        SuccessButton(btn_bar, "➕ 添加书籍", command=self._show_add_book_dialog, width=130).pack(side="left", padx=4)
        PrimaryButton(btn_bar, "📤 发布章节", command=self._show_publish_dialog, width=130).pack(side="left", padx=4)
        GhostButton(btn_bar, "🔄 刷新", command=self._refresh_books, width=100).pack(side="left", padx=4)

        table_frame = ctk.CTkFrame(self.content_frame, fg_color=Colors.BG_CARD, corner_radius=12)
        table_frame.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        columns = ("id", "account", "name", "fanqie_id", "chapters", "status")
        headings = ("ID", "账号", "书名", "番茄书籍ID", "章节数", "状态")
        widths = (60, 100, 220, 160, 80, 100)
        self.books_tree = TreeviewFrame(table_frame, columns, headings, widths)
        self.books_tree.pack(fill="both", expand=True, padx=12, pady=12)

        self._refresh_books()

    def _show_chapters(self):
        """显示章节列表页面"""
        self._clear_content()
        self.current_view = "chapters"
        self._set_active_nav("chapters")

        self._create_page_header("📖 章节列表", "查看和管理书籍章节")

        # 筛选栏
        filter_bar = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        filter_bar.pack(fill="x", padx=24, pady=(16, 12))

        ctk.CTkLabel(filter_bar, text="选择书籍:", text_color=Colors.TEXT_SECONDARY).pack(side="left", padx=(0, 10))

        self.chapter_book_var = ctk.StringVar()
        self.chapter_book_combo = ModernComboBox(filter_bar, width=300)
        self.chapter_book_combo.pack(side="left", padx=4)
        self.chapter_book_combo.configure(command=self._on_chapter_book_changed)

        GhostButton(filter_bar, "🔄 刷新", command=self._refresh_chapters, width=100).pack(side="left", padx=4)

        table_frame = ctk.CTkFrame(self.content_frame, fg_color=Colors.BG_CARD, corner_radius=12)
        table_frame.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        columns = ("id", "number", "title", "words", "status")
        headings = ("ID", "章节号", "章节标题", "字数", "状态")
        widths = (60, 80, 400, 100, 100)
        self.chapters_tree = TreeviewFrame(table_frame, columns, headings, widths)
        self.chapters_tree.pack(fill="both", expand=True, padx=12, pady=12)

        self._refresh_books_for_chapters()

    def _show_accounts(self):
        """显示账号管理页面"""
        self._clear_content()
        self.current_view = "accounts"
        self._set_active_nav("accounts")

        self._create_page_header("👤 账号管理", "管理番茄写作账号")

        btn_bar = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        btn_bar.pack(fill="x", padx=24, pady=(16, 12))

        SuccessButton(btn_bar, "🔐 登录账号", command=self._show_login_dialog, width=130).pack(side="left", padx=4)
        GhostButton(btn_bar, "🔄 刷新", command=self._refresh_accounts, width=100).pack(side="left", padx=4)

        table_frame = ctk.CTkFrame(self.content_frame, fg_color=Colors.BG_CARD, corner_radius=12)
        table_frame.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        columns = ("id", "name", "phone", "status", "last_login")
        headings = ("ID", "名称", "手机号", "状态", "最后登录")
        widths = (60, 160, 140, 120, 180)
        self.accounts_tree = TreeviewFrame(table_frame, columns, headings, widths)
        self.accounts_tree.pack(fill="both", expand=True, padx=12, pady=12)

        self._refresh_accounts()

    def _show_logs(self):
        """显示发布日志页面"""
        self._clear_content()
        self.current_view = "logs"
        self._set_active_nav("logs")

        self._create_page_header("📊 发布日志", "查看章节发布记录")

        GhostButton(self.content_frame, "🔄 刷新", command=self._refresh_logs, width=100).pack(anchor="e", padx=24, pady=(16, 8))

        table_frame = ctk.CTkFrame(self.content_frame, fg_color=Colors.BG_CARD, corner_radius=12)
        table_frame.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        columns = ("id", "chapter", "account", "action", "status", "message", "time")
        headings = ("ID", "章节", "账号", "操作", "状态", "消息", "时间")
        widths = (60, 240, 100, 90, 100, 260, 160)
        self.logs_tree = TreeviewFrame(table_frame, columns, headings, widths)
        self.logs_tree.pack(fill="both", expand=True, padx=12, pady=12)

        self._refresh_logs()

    def _show_feishu_config(self):
        """显示飞书配置页面"""
        self._clear_content()
        self.current_view = "feishu"
        self._set_active_nav("feishu")

        self._create_page_header("🔔 飞书配置", "配置飞书群通知")

        # 配置卡片
        config_card = ModernCard(self.content_frame, title="通知设置")
        config_card.pack(fill="x", padx=24, pady=(16, 12))

        # Webhook URL
        row1 = ctk.CTkFrame(config_card, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=12)

        ctk.CTkLabel(row1, text="Webhook地址:", width=120, anchor="w",
                    text_color=Colors.TEXT_SECONDARY).pack(side="left")
        self.feishu_webhook_entry = ModernEntry(row1, width=500,
                    placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxx")
        self.feishu_webhook_entry.pack(side="left", padx=10, fill="x", expand=True)

        # 启用开关
        row2 = ctk.CTkFrame(config_card, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=12)

        ctk.CTkLabel(row2, text="启用通知:", width=120, anchor="w",
                    text_color=Colors.TEXT_SECONDARY).pack(side="left")
        self.feishu_enabled_switch = ModernSwitch(row2, text="")
        self.feishu_enabled_switch.pack(side="left", padx=10)

        # 按钮
        btn_row = ctk.CTkFrame(config_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(12, 20))

        SuccessButton(btn_row, "💾 保存配置", command=self._save_feishu_config, width=130).pack(side="left", padx=4)
        PrimaryButton(btn_row, "🧪 发送测试", command=self._test_feishu_notification, width=130).pack(side="left", padx=4)

        # 测试结果
        self.feishu_test_result = ctk.CTkLabel(
            self.content_frame, text="", text_color=Colors.TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 12)
        )
        self.feishu_test_result.pack(pady=8)

        # 说明卡片
        help_card = ModernCard(self.content_frame, title="使用说明")
        help_card.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        help_text = """📌 获取飞书Webhook地址：

1. 在飞书群中添加"自定义机器人"
2. 复制机器人 Webhook 地址
3. 粘贴到上方输入框并保存

📬 通知内容：
• 书名
• 章节名称
• 发布状态
• 发布时间"""

        help_label = ctk.CTkLabel(
            help_card, text=help_text, justify="left", padx=20, pady=16,
            font=("Microsoft YaHei UI", 13), text_color=Colors.TEXT_SECONDARY
        )
        help_label.pack(fill="both", expand=True)

        # 加载配置
        self._load_feishu_config()

    def _create_page_header(self, title, subtitle):
        """创建页面标题"""
        header = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=20)

        title_label = ctk.CTkLabel(
            header,
            text=title,
            font=("Microsoft YaHei UI", 26, "bold"),
            text_color=Colors.TEXT_PRIMARY
        )
        title_label.pack(anchor="w")

        subtitle_label = ctk.CTkLabel(
            header,
            text=subtitle,
            font=("Microsoft YaHei UI", 13),
            text_color=Colors.TEXT_MUTED
        )
        subtitle_label.pack(anchor="w", pady=(4, 0))

    # ==================== 刷新方法 ====================

    def _refresh_all(self):
        """刷新所有数据"""
        self._update_status()

    def _refresh_tasks(self):
        """刷新任务列表"""
        if not hasattr(self, 'tasks_tree'):
            return
        self.tasks_tree.clear()

        db = get_session()
        try:
            tasks = db.query(PendingTask).order_by(PendingTask.scheduled_time).all()
            for task in tasks:
                account_name = book_name = chapter_title = ""

                if task.chapter:
                    chapter_title = task.chapter.chapter_title
                    if task.chapter.book:
                        book_name = task.chapter.book.book_name
                        if task.chapter.book.account:
                            account_name = task.chapter.book.account.name

                scheduled = task.scheduled_time.strftime("%Y-%m-%d %H:%M") if task.scheduled_time else ""

                status_map = {
                    "pending": ("⏳ 待发布", "pending"),
                    "publishing": ("🔄 发布中", "publishing"),
                    "published": ("✅ 已发布", "published"),
                    "cancelled": ("❌ 已取消", "failed")
                }
                status_info = status_map.get(task.status, (task.status, "pending"))

                self.tasks_tree.insert((task.id, account_name, book_name, chapter_title, scheduled, status_info[0]))
        finally:
            db.close()

        self._update_status(f"已刷新 ({datetime.now().strftime('%H:%M:%S')})")

    def _refresh_books(self):
        """刷新书籍列表"""
        if not hasattr(self, 'books_tree'):
            return
        self.books_tree.clear()

        db = get_session()
        try:
            books = db.query(Book).all()
            for book in books:
                account_name = book.account.name if book.account else "未分配"
                chapter_count = db.query(Chapter).filter_by(book_id=book.id).count()
                status_text = "✅ 正常" if book.status == "active" else "❌ 停用"
                status_type = "active" if book.status == "active" else "failed"
                self.books_tree.insert((book.id, account_name, book.book_name,
                                       book.fanqie_book_id or "未设置", chapter_count, status_text))
        finally:
            db.close()

    def _refresh_books_for_chapters(self):
        """刷新书籍选择框"""
        db = get_session()
        try:
            books = db.query(Book).all()
            values = ["-- 请选择书籍 --"]
            for book in books:
                values.append(f"{book.id}: {book.book_name}")
            if hasattr(self, 'chapter_book_combo'):
                self.chapter_book_combo.configure(values=values)
                if values:
                    self.chapter_book_combo.set(values[0])
        finally:
            db.close()

    def _refresh_chapters(self):
        """刷新章节列表"""
        if not hasattr(self, 'chapters_tree'):
            return
        self.chapters_tree.clear()

        book_id = self.chapter_book_var.get().split(":")[0]
        if not book_id or not book_id.isdigit():
            return

        db = get_session()
        try:
            chapters = db.query(Chapter).filter_by(book_id=int(book_id)).order_by(Chapter.chapter_number).all()
            status_map = {
                "pending": ("⏳ 待发布", "pending"),
                "publishing": ("🔄 发布中", "publishing"),
                "published": ("✅ 已发布", "published"),
                "failed": ("❌ 失败", "failed")
            }
            for ch in chapters:
                status_info = status_map.get(ch.status, (ch.status, "pending"))
                self.chapters_tree.insert((ch.id, ch.chapter_number, ch.chapter_title,
                                          ch.word_count or 0, status_info[0]))
        finally:
            db.close()

    def _refresh_accounts(self):
        """刷新账号列表"""
        if not hasattr(self, 'accounts_tree'):
            return
        self.accounts_tree.clear()

        db = get_session()
        try:
            accounts = db.query(Account).all()
            status_map = {
                "active": ("✅ 已登录", "active"),
                "inactive": ("❌ 未登录", "inactive"),
                "session_expired": ("⚠️ 已过期", "pending")
            }
            for acc in accounts:
                last_login = acc.last_login.strftime("%Y-%m-%d %H:%M") if acc.last_login else "从未登录"
                status_info = status_map.get(acc.status, (acc.status, "inactive"))
                self.accounts_tree.insert((acc.id, acc.name, acc.phone or "-",
                                           status_info[0], last_login))
        finally:
            db.close()

    def _refresh_logs(self):
        """刷新日志列表"""
        if not hasattr(self, 'logs_tree'):
            return
        self.logs_tree.clear()

        db = get_session()
        try:
            logs = db.query(PublishLog).order_by(PublishLog.created_at.desc()).limit(100).all()
            status_map = {
                "success": ("✅ 成功", "active"),
                "failed": ("❌ 失败", "failed"),
                "skipped": ("⏭️ 跳过", "pending"),
                "session_expired": ("⚠️ 过期", "pending")
            }
            for log in logs:
                chapter_title = log.chapter.chapter_title if log.chapter else f"章节{log.chapter_id}"
                account_name = log.account.name if log.account else f"账号{log.account_id}"
                created_at = log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else ""
                status_info = status_map.get(log.status, (log.status, "pending"))
                self.logs_tree.insert((log.id, chapter_title[:35], account_name, log.action,
                                      status_info[0], (log.message or "")[:40], created_at))
        finally:
            db.close()

    def _update_status(self, msg="系统就绪"):
        """更新状态栏"""
        if hasattr(self, 'header_status'):
            self.header_status.configure(text=msg)

    # ==================== 对话框 ====================

    def _show_add_task_dialog(self):
        """添加任务对话框"""
        dialog = ModernDialog(self, "添加待发布任务", 420, 300)

        ctk.CTkLabel(dialog.content_frame, text="章节ID:",
                    text_color=Colors.TEXT_SECONDARY).pack(anchor="w", pady=(0, 8))
        chapter_var = ctk.StringVar()
        ModernEntry(dialog.content_frame, textvariable=chapter_var, placeholder="输入章节ID").pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(dialog.content_frame, text="发布时间:",
                    text_color=Colors.TEXT_SECONDARY).pack(anchor="w", pady=(0, 8))
        time_var = ctk.StringVar(value="+1")
        ModernEntry(dialog.content_frame, textvariable=time_var, placeholder="+1, +30m, 20:00").pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(dialog.content_frame, text="格式: +1(1分钟后), +30m, 20:00, 2024-03-29 20:00",
                    text_color=Colors.TEXT_MUTED, font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(0, 16))

        def do_add():
            try:
                chapter_id = int(chapter_var.get())
                time_str = time_var.get()
                scheduled_time = self._parse_time(time_str)
                if not scheduled_time:
                    self._update_status("时间格式错误")
                    return

                with safe_session() as db:
                    task = PendingTask(chapter_id=chapter_id, scheduled_time=scheduled_time, status="pending")
                    db.add(task)
                dialog.destroy()
                self._refresh_tasks()
                self._update_status(f"已添加任务 #{chapter_id}")

            except ValueError:
                self._update_status("章节ID必须是数字")

        PrimaryButton(dialog.content_frame, "添加", command=do_add, width=120).pack(pady=(8, 0))

    def _show_add_book_dialog(self):
        """添加书籍对话框"""
        dialog = ModernDialog(self, "添加书籍", 500, 420)

        db = get_session()
        try:
            accounts = db.query(Account).all()
            account_values = [f"{a.id}: {a.name}" for a in accounts]
        finally:
            db.close()

        ctk.CTkLabel(dialog.content_frame, text="选择账号:",
                    text_color=Colors.TEXT_SECONDARY).pack(anchor="w", pady=(0, 8))
        account_var = ctk.StringVar()
        ModernComboBox(dialog.content_frame, values=account_values, variable=account_var).pack(fill="x", pady=(0, 16))

        name_var = ctk.StringVar()
        fanqie_id_var = ctk.StringVar()
        folder_var = ctk.StringVar()

        for label, var, placeholder in [
            ("书籍名称:", name_var, "输入书籍名称"),
            ("番茄书籍ID:", fanqie_id_var, "留空自动获取"),
            ("本地文件夹:", folder_var, "输入本地文件夹路径")
        ]:
            ctk.CTkLabel(dialog.content_frame, text=label, text_color=Colors.TEXT_SECONDARY).pack(anchor="w", pady=(0, 8))
            ModernEntry(dialog.content_frame, textvariable=var, placeholder=placeholder).pack(fill="x", pady=(0, 16))

        def do_add():
            try:
                account_id = int(account_var.get().split(":")[0])
                book_name = name_var.get().strip()
                if not book_name:
                    self._update_status("书名不能为空")
                    return

                with safe_session() as db:
                    book = Book(
                        account_id=account_id,
                        book_name=book_name,
                        fanqie_book_id=fanqie_id_var.get().strip() or None,
                        local_folder=folder_var.get().strip() or None,
                        status="active"
                    )
                    db.add(book)
                dialog.destroy()
                self._refresh_books()
                self._update_status("已添加书籍")

            except (ValueError, IndexError) as e:
                self._update_status(f"添加失败: {e}")

        SuccessButton(dialog.content_frame, "添加", command=do_add, width=120).pack(pady=(8, 0))

    def _show_publish_dialog(self):
        """发布对话框"""
        book_id = self.books_tree.get_selection()
        if not book_id:
            self._update_status("请先选择要发布的书籍")
            return

        db = get_session()
        try:
            book = db.query(Book).filter_by(id=book_id).first()
            if not book:
                return
            book_name = book.book_name
        finally:
            db.close()

        dialog = ModernDialog(self, f"发布 - {book_name}", 420, 340)

        ctk.CTkLabel(dialog.content_frame, text=f"书籍: {book_name}",
                    font=("Microsoft YaHei UI", 16, "bold"), text_color=Colors.TEXT_PRIMARY).pack(pady=(0, 16))

        ctk.CTkLabel(dialog.content_frame, text="选择章节:",
                    text_color=Colors.TEXT_SECONDARY).pack(anchor="w", pady=(0, 8))
        chapters_var = ctk.StringVar(value="all")
        ModernEntry(dialog.content_frame, textvariable=chapters_var, placeholder="1,2,3 或 1-5 或 all").pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(dialog.content_frame, text="起始时间:",
                    text_color=Colors.TEXT_SECONDARY).pack(anchor="w", pady=(0, 8))
        time_var = ctk.StringVar(value="+1")
        ModernEntry(dialog.content_frame, textvariable=time_var, placeholder="+1, +30m, 20:00").pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(dialog.content_frame, text="多章节会自动错开1-2分钟发布",
                    text_color=Colors.TEXT_MUTED, font=("Microsoft YaHei UI", 11)).pack(pady=(0, 16))

        def do_publish():
            selection = chapters_var.get().strip()
            start_time = self._parse_time(time_var.get())
            if not start_time:
                self._update_status("时间格式错误")
                return

            import random
            from datetime import timedelta

            try:
                with safe_session() as db:
                    if selection.lower() == "all":
                        chapters = db.query(Chapter).filter_by(book_id=book_id, status="pending").order_by(Chapter.chapter_number).all()
                    else:
                        chapter_ids = self._parse_chapter_selection(selection)
                        chapters = db.query(Chapter).filter(Chapter.book_id == book_id, Chapter.id.in_(chapter_ids)).order_by(Chapter.chapter_number).all()

                    if not chapters:
                        self._update_status("没有待发布的章节")
                        return

                    current_time = start_time
                    added = 0

                    for i, ch in enumerate(chapters):
                        existing = db.query(PendingTask).filter_by(chapter_id=ch.id, status="pending").first()
                        if existing:
                            continue
                        db.add(PendingTask(chapter_id=ch.id, scheduled_time=current_time, status="pending"))
                        added += 1
                        if i < len(chapters) - 1:
                            current_time = current_time + timedelta(seconds=random.randint(PUBLISH_DELAY_MIN, PUBLISH_DELAY_MAX))

                dialog.destroy()
                self._refresh_tasks()
                self._update_status(f"已添加 {added} 个章节")

            except Exception as e:
                self._update_status(f"发布失败: {e}")

        PrimaryButton(dialog.content_frame, "发布", command=do_publish, width=120).pack(pady=(8, 0))

    def _show_login_dialog(self):
        """登录对话框"""
        account_id = self.accounts_tree.get_selection()
        if not account_id:
            self._update_status("请先选择要登录的账号")
            return

        db = get_session()
        try:
            account = db.query(Account).filter_by(id=account_id).first()
            if not account:
                self._update_status("账号不存在")
                return
            account_name = account.name
        finally:
            db.close()

        dialog = ModernDialog(self, f"登录 - {account_name}", 320, 160)

        ctk.CTkLabel(dialog.content_frame, text=f"账号: {account_name}",
                    font=("Microsoft YaHei UI", 15), text_color=Colors.TEXT_PRIMARY).pack(pady=16)
        ctk.CTkLabel(dialog.content_frame, text="正在启动浏览器...",
                    text_color=Colors.TEXT_SECONDARY).pack()

        def do_login():
            from browser.fanqie.login import login_with_browser
            try:
                success = browser_manager._run_async(login_with_browser(account_id))
                self.after(0, lambda: on_complete(success))
            except Exception as e:
                self.after(0, lambda: on_complete(False, error=str(e)))

        def on_complete(success, error=None):
            dialog.destroy()
            self._refresh_accounts()
            if success:
                self._update_status(f"账号 {account_name} 登录成功")
            else:
                self._update_status(f"登录失败: {error or '未知错误'}")

        threading.Thread(target=do_login, daemon=True).start()

    def _delete_selected_tasks(self):
        """删除选中任务"""
        task_ids = self.tasks_tree.get_all_selections()
        if not task_ids:
            self._update_status("请先选择要删除的任务")
            return

        db = get_session()
        try:
            count = 0
            for task_id in task_ids:
                task = db.query(PendingTask).filter_by(id=task_id).first()
                if task:
                    db.delete(task)
                    count += 1
            db.commit()
            self._refresh_tasks()
            self._update_status(f"已删除 {count} 个任务")
        finally:
            db.close()

    def _on_chapter_book_changed(self, choice):
        """书籍选择改变"""
        if choice and choice != "-- 请选择书籍 --":
            self.chapter_book_var.set(choice)
            self._refresh_chapters()

    # ==================== 飞书配置方法 ====================

    def _load_feishu_config(self):
        """加载飞书配置"""
        try:
            from database.connection import get_session
            from database.models import FeishuConfig as FeishuConfigModel

            db = get_session()
            try:
                config = db.query(FeishuConfigModel).first()
                if config:
                    self.feishu_webhook_entry.delete(0, "end")
                    self.feishu_webhook_entry.insert(0, config.webhook_url or "")
                    if config.enabled:
                        self.feishu_enabled_switch.select()
                    else:
                        self.feishu_enabled_switch.deselect()
                else:
                    self.feishu_webhook_entry.delete(0, "end")
                    self.feishu_enabled_switch.deselect()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"加载飞书配置失败: {e}")

    def _save_feishu_config(self):
        """保存飞书配置"""
        try:
            from database.connection import get_session
            from database.models import FeishuConfig as FeishuConfigModel
            from utils.feishu import FeishuConfig, get_feishu_notifier

            webhook_url = self.feishu_webhook_entry.get().strip()
            enabled = self.feishu_enabled_switch.get() == 1

            db = get_session()
            try:
                config = db.query(FeishuConfigModel).first()
                if not config:
                    config = FeishuConfigModel()
                    db.add(config)

                config.webhook_url = webhook_url
                config.enabled = enabled
                db.commit()

                # 更新全局通知器
                notifier = get_feishu_notifier()
                notifier.set_config(FeishuConfig(
                    app_id="",
                    app_secret="",
                    webhook_url=webhook_url,
                    enabled=enabled
                ))

                self._update_status("✅ 飞书配置已保存")
                self.feishu_test_result.configure(text="配置已保存", text_color=Colors.ACCENT_GREEN)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"保存飞书配置失败: {e}")
            self.feishu_test_result.configure(text=f"保存失败: {e}", text_color=Colors.ACCENT_RED)

    def _test_feishu_notification(self):
        """发送测试通知"""
        try:
            from utils.feishu import FeishuConfig, get_feishu_notifier

            webhook_url = self.feishu_webhook_entry.get().strip()
            if not webhook_url:
                self.feishu_test_result.configure(text="请先填写Webhook地址", text_color=Colors.ACCENT_RED)
                return

            notifier = get_feishu_notifier()
            notifier.set_config(FeishuConfig(
                app_id="",
                app_secret="",
                webhook_url=webhook_url,
                enabled=True
            ))

            success = notifier.send_publish_success(
                book_name="测试书籍",
                chapter_title="第一章 测试章节",
                publish_time=datetime.now()
            )

            if success:
                self.feishu_test_result.configure(text="✅ 测试通知发送成功！请检查飞书群", text_color=Colors.ACCENT_GREEN)
            else:
                self.feishu_test_result.configure(text="❌ 发送失败，请检查Webhook地址", text_color=Colors.ACCENT_RED)
        except Exception as e:
            logger.error(f"发送测试通知失败: {e}")
            self.feishu_test_result.configure(text=f"发送失败: {e}", text_color=Colors.ACCENT_RED)

    # ==================== 辅助方法 ====================

    def _clear_content(self):
        """清空内容区"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _start_scheduler(self):
        """启动任务调度器"""
        task_scheduler.start()

    def _start_auto_refresh(self):
        """启动自动刷新"""
        self.after(10000, self._auto_refresh)

    def _auto_refresh(self):
        """自动刷新"""
        if hasattr(self, 'current_view'):
            if self.current_view == "tasks":
                self._refresh_tasks()
        self._start_auto_refresh()

    def _parse_time(self, time_str):
        """解析时间字符串"""
        import re
        from datetime import datetime, timedelta

        time_str = time_str.strip()

        if time_str.startswith('+'):
            match = re.match(r'\+(\d+)([hmd])?', time_str)
            if match:
                value = int(match.group(1))
                unit = match.group(2) or 'm'
                now = datetime.now()
                if unit == 'h':
                    return now + timedelta(hours=value)
                elif unit == 'd':
                    return now + timedelta(days=value)
                else:
                    return now + timedelta(minutes=value)

        match = re.match(r'(\d{1,2}):(\d{2})', time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            now = datetime.now()
            result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result <= now:
                result += timedelta(days=1)
            return result

        for fmt in ['%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S']:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        return datetime.now() + timedelta(minutes=1)

    def _parse_chapter_selection(self, selection):
        """解析章节选择"""
        import re
        chapter_ids = []
        for part in selection.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    start, end = part.split("-")
                    for i in range(int(start), int(end) + 1):
                        chapter_ids.append(i)
                except ValueError:
                    pass
            else:
                try:
                    chapter_ids.append(int(part))
                except ValueError:
                    pass
        return chapter_ids

    def _on_close(self):
        """关闭应用"""
        self._update_status("正在关闭...")
        task_scheduler.stop()
        browser_manager.stop()
        self.destroy()


def main():
    """主入口"""
    app = FanqieApp()
    app.mainloop()


if __name__ == "__main__":
    main()
