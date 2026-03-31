import os
from pathlib import Path

import chardet


def read_file_content(file_path: str) -> str:
    """读取文件内容，自动检测编码"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    # 尝试常用编码
    for encoding in ["utf-8", "gbk", "gb2312", "utf-8-sig"]:
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    # 回退: chardet自动检测
    raw_data = path.read_bytes()
    detected = chardet.detect(raw_data)
    encoding = detected.get("encoding", "utf-8")
    return raw_data.decode(encoding, errors="replace")


def count_words(text: str) -> int:
    """统计中文字数（去掉空白字符）"""
    return len(text.replace(" ", "").replace("\n", "").replace("\r", "").replace("\t", ""))


def normalize_path(path_str: str) -> str:
    """规范化路径（Windows兼容）"""
    return str(Path(path_str).resolve())


def ensure_dir(dir_path: str):
    """确保目录存在"""
    Path(dir_path).mkdir(parents=True, exist_ok=True)
