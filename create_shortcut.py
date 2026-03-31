#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创建桌面快捷方式
"""
import os
import sys
from pathlib import Path

try:
    import win32com.client
    import pythoncom
except ImportError:
    print("正在安装 pywin32...")
    os.system("pip install pywin32")
    import win32com.client
    import pythoncom


def create_shortcut():
    """创建桌面快捷方式"""
    script_dir = Path(__file__).parent.resolve()
    python_path = sys.executable
    batch_file = script_dir / "桌面版.bat"
    icon_file = script_dir / "icon.ico"

    # 快捷方式路径
    desktop = Path(os.path.expandvars("%USERPROFILE%/Desktop"))
    shortcut_path = desktop / "番茄小说自动发布器.lnk"

    print(f"脚本目录: {script_dir}")
    print(f"快捷方式路径: {shortcut_path}")

    try:
        # 初始化COM
        pythoncom.CoInitialize()

        # 创建快捷方式
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(shortcut_path))

        shortcut.TargetPath = str(batch_file)
        shortcut.WorkingDirectory = str(script_dir)
        shortcut.Description = "番茄小说自动发布器"
        shortcut.WindowStyle = 1  # 正常窗口

        # 如果有图标就设置
        if icon_file.exists():
            shortcut.IconLocation = str(icon_file)

        shortcut.Save()

        print(f"\n[成功] 已在桌面创建快捷方式!")
        print(f"快捷方式位置: {shortcut_path}")

    except Exception as e:
        print(f"[错误] 创建快捷方式失败: {e}")
        print("\n请手动创建快捷方式:")
        print(f"  1. 右键点击 '桌面版.bat'")
        print(f"  2. 选择 '创建快捷方式'")
        print(f"  3. 将快捷方式移动到桌面")
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    create_shortcut()
    input("\n按回车键退出...")
