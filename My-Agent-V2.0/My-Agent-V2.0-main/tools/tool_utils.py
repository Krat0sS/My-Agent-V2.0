"""
工具共享函数 — 从 builtin.py 提取的通用工具函数
供各插件文件导入使用
"""
import os
import json
import shutil
import datetime
import platform
import time
import hashlib
import glob as glob_mod


# ═══ 工具缓存 ═══

CACHEABLE_TOOLS = {
    "read_file", "list_files", "ab_open", "ab_screenshot",
    "ab_get_text", "ab_get_html", "ab_get_title", "ab_get_url",
    "recall",
}

_cache: dict = {}  # key -> (expire_timestamp, result)

_DEFAULT_CACHE_TTL = 300  # 5 分钟兜底


def _get_cache_ttl() -> int:
    try:
        import config
        return getattr(config, 'TOOL_CACHE_TTL', _DEFAULT_CACHE_TTL)
    except ImportError:
        return _DEFAULT_CACHE_TTL


def cache_key(func_name: str, args: dict) -> str:
    raw = f"{func_name}:{json.dumps(args, sort_keys=True)}"
    return hashlib.md5(raw.encode()).hexdigest()


def cache_get(func_name: str, args: dict):
    ttl = _get_cache_ttl()
    if ttl <= 0:
        return None
    key = cache_key(func_name, args)
    entry = _cache.get(key)
    if entry is None:
        return None
    expire_ts, result = entry
    if time.time() > expire_ts:
        del _cache[key]
        return None
    try:
        parsed = json.loads(result)
        parsed["_cached"] = True
        return json.dumps(parsed, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return result


def cache_set(func_name: str, args: dict, result: str):
    ttl = _get_cache_ttl()
    if ttl <= 0:
        return
    key = cache_key(func_name, args)
    _cache[key] = (time.time() + ttl, result)


# ═══ 结构化错误 ═══

def structured_error(error_type: str, message: str, hint: str = "",
                     recoverable: bool = False, **extra) -> str:
    """
    生成结构化错误响应。
    Agent 拿到这个 JSON 后能自动判断：是否可恢复、该怎么向用户解释。
    """
    result = {
        "error": True,
        "type": error_type,
        "message": message,
        "recoverable": recoverable,
        "display_hint": hint or message,
    }
    result.update(extra)
    return json.dumps(result, ensure_ascii=False)


def classify_os_error(e: OSError, path: str) -> str:
    """将 OSError 分类为用户友好的结构化错误"""
    errno = getattr(e, 'errno', None)
    msg = str(e).lower()

    if errno == 13 or 'permission' in msg or 'access' in msg:
        return structured_error(
            "permission_denied", f"没有权限访问: {path}",
            hint="文件可能被其他程序占用，或你没有访问权限。关闭占用该文件的程序后重试。",
            recoverable=True, path=path
        )
    elif errno == 28 or 'no space' in msg or 'disk' in msg:
        return structured_error(
            "disk_full", f"磁盘空间不足，无法写入: {path}",
            hint="磁盘满了。清理一些文件后重试。可以用 find_files 找大文件删除。",
            recoverable=True, path=path
        )
    elif errno == 36 or 'file name' in msg or 'too long' in msg:
        return structured_error(
            "filename_too_long", f"文件名过长: {path}",
            hint="文件名超过系统限制（通常 255 字符）。请缩短文件名。",
            recoverable=True, path=path
        )
    elif errno == 18 or 'cross-device' in msg or 'invalid' in msg:
        return structured_error(
            "cross_device", f"跨设备移动失败: {path}",
            hint="源和目标不在同一个磁盘分区。将使用复制+删除方式重试。",
            recoverable=True, path=path
        )
    else:
        return structured_error(
            "os_error", f"文件操作失败: {e}",
            hint=f"操作系统错误。路径: {path}",
            recoverable=False, path=path, errno=errno
        )


# ═══ 文件分类 ═══

_EXT_CATEGORIES = {
    # 文档
    ".doc": "文档", ".docx": "文档", ".pdf": "文档", ".txt": "文档",
    ".rtf": "文档", ".odt": "文档", ".md": "文档", ".tex": "文档",
    ".xls": "文档", ".xlsx": "文档", ".csv": "文档", ".ppt": "文档",
    ".pptx": "文档", ".pages": "文档", ".numbers": "文档", ".key": "文档",
    # 代码
    ".py": "代码", ".js": "代码", ".ts": "代码", ".java": "代码",
    ".c": "代码", ".cpp": "代码", ".h": "代码", ".cs": "代码",
    ".go": "代码", ".rs": "代码", ".rb": "代码", ".php": "代码",
    ".swift": "代码", ".kt": "代码", ".scala": "代码", ".r": "代码",
    ".m": "代码", ".sh": "代码", ".bat": "代码", ".ps1": "代码",
    ".html": "代码", ".css": "代码", ".scss": "代码", ".vue": "代码",
    ".jsx": "代码", ".tsx": "代码", ".json": "代码", ".xml": "代码",
    ".yaml": "代码", ".yml": "代码", ".toml": "代码", ".ini": "代码",
    ".sql": "代码", ".db": "代码", ".sqlite": "代码",
    # 图片
    ".jpg": "图片", ".jpeg": "图片", ".png": "图片", ".gif": "图片",
    ".bmp": "图片", ".svg": "图片", ".webp": "图片", ".ico": "图片",
    ".tiff": "图片", ".tif": "图片", ".heic": "图片", ".heif": "图片",
    ".psd": "图片", ".ai": "图片", ".eps": "图片", ".raw": "图片",
    # 视频
    ".mp4": "视频", ".avi": "视频", ".mkv": "视频", ".mov": "视频",
    ".wmv": "视频", ".flv": "视频", ".webm": "视频", ".m4v": "视频",
    ".mpg": "视频", ".mpeg": "视频", ".3gp": "视频",
    # 音频
    ".mp3": "音频", ".wav": "音频", ".flac": "音频", ".aac": "音频",
    ".ogg": "音频", ".wma": "音频", ".m4a": "音频", ".opus": "音频",
    ".mid": "音频", ".midi": "音频",
    # 压缩包
    ".zip": "压缩包", ".rar": "压缩包", ".7z": "压缩包", ".tar": "压缩包",
    ".gz": "压缩包", ".bz2": "压缩包", ".xz": "压缩包", ".tgz": "压缩包",
    # 可执行/安装
    ".exe": "程序", ".msi": "程序", ".dmg": "程序", ".app": "程序",
    ".deb": "程序", ".rpm": "程序", ".apk": "程序", ".ipa": "程序",
    ".jar": "程序", ".war": "程序",
    # 种子/下载
    ".torrent": "下载", ".metalink": "下载",
}


def categorize_file(filename: str) -> str:
    """根据扩展名自动分类文件"""
    ext = os.path.splitext(filename)[1].lower()
    return _EXT_CATEGORIES.get(ext, "其他")


# ═══ 跨平台工具 ═══

def get_special_folder(folder_name: str) -> str:
    """获取跨平台特殊目录（桌面、下载等）"""
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            if folder_name == "Desktop":
                path = winreg.QueryValueEx(key, "Desktop")[0]
            elif folder_name == "Downloads":
                path = os.path.join(os.path.expanduser("~"), "Downloads")
            else:
                path = os.path.expanduser(f"~/{folder_name}")
            winreg.CloseKey(key)
            if os.path.exists(path):
                return path
        except Exception:
            pass
    return os.path.expanduser(f"~/{folder_name}")


def human_size(size_bytes: int) -> str:
    """人类可读的文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


# ═══ 统一工具结果 ═══

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolResult:
    """
    统一工具返回结构 — 所有工具 handler 必须返回这个结构的 JSON。

    字段说明：
    - success: 是否成功（核心判断字段，替代之前的多种判断方式）
    - data: 成功时的返回数据（任意类型）
    - error: 失败时的错误信息
    - error_code: 错误码（用于 LLM 自动决策：E_NOT_FOUND / E_PERMISSION / E_TIMEOUT / E_ENCODING / E_UNKNOWN）
    - recoverable: 是否可恢复（True → LLM 应该重试或换方案，False → 直接告诉用户）
    - hint: 给 LLM 的提示（如何恢复、用什么替代方案）
    - display_hint: 给用户的提示（可选，不填则用 message）
    """
    success: bool = True
    data: Optional[dict] = None
    error: Optional[str] = None
    error_code: str = ""
    recoverable: bool = True
    hint: str = ""
    display_hint: str = ""
    extra: dict = field(default_factory=dict)

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        result = {"success": self.success}
        if self.data is not None:
            result["data"] = self.data
        if self.error:
            result["error"] = self.error
        if self.error_code:
            result["error_code"] = self.error_code
        if not self.success:
            result["recoverable"] = self.recoverable
        if self.hint:
            result["hint"] = self.hint
        if self.display_hint:
            result["display_hint"] = self.display_hint
        result.update(self.extra)
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def ok(data: dict = None, **extra) -> str:
        """成功结果快捷方法"""
        r = ToolResult(success=True, data=data or {}, extra=extra)
        return r.to_json()

    @staticmethod
    def fail(error: str, error_code: str = "E_UNKNOWN",
             recoverable: bool = True, hint: str = "", **extra) -> str:
        """失败结果快捷方法"""
        r = ToolResult(
            success=False, error=error, error_code=error_code,
            recoverable=recoverable, hint=hint, extra=extra,
        )
        return r.to_json()


def normalize_path(path: str) -> str:
    """
    路径规范化：Unicode NFC + 展开 ~ + 统一斜杠。
    解决中文路径在不同平台下的编码不一致问题。
    """
    import unicodedata
    path = os.path.expanduser(path)
    path = unicodedata.normalize('NFC', path)
    return path


# ═══ 工具方法类别（用于同类错误归类） ═══

TOOL_CATEGORIES = {
    # DOM 交互类 — 操作页面元素（一个失败，同类大概率也失败）
    "dom_interact": [
        "ab_click", "ab_fill", "ab_type", "ab_press", "ab_dblclick",
        "ab_hover", "ab_select", "ab_check", "ab_uncheck", "ab_scrollintoview",
        "ab_drag", "ab_find",
    ],
    # DOM 观察类 — 读取页面信息
    "dom_observe": [
        "ab_snapshot", "ab_screenshot", "ab_get_text", "ab_get_html",
        "ab_get_value", "ab_get_attr", "ab_get_title", "ab_get_url",
        "ab_is_visible",
    ],
    # URL 导航类 — 打开/搜索
    "url_navigate": [
        "ab_open", "ab_navigate_and_snapshot", "ab_snapshot_click",
        "web_search", "ddg_search", "news_search",
    ],
    # 文件操作类
    "file_ops": [
        "read_file", "write_file", "edit_file", "move_file",
        "list_files", "scan_files", "find_files", "batch_move",
        "organize_directory", "rollback_operation",
    ],
    # 命令执行类
    "command": [
        "run_command", "run_command_confirmed",
    ],
    # Git 操作类
    "git": [
        "git_status", "git_diff", "git_add", "git_commit",
        "git_push", "git_restore", "git_last_test",
    ],
    # 记忆类
    "memory": [
        "remember", "recall", "set_preference",
    ],
    # 视觉类
    "vision": [
        "vision_analyze", "task_plan",
    ],
    # 浏览器生命周期
    "browser_lifecycle": [
        "ab_close", "ab_connect", "ab_pdf", "ab_eval", "ab_wait",
        "ab_scroll",
    ],
    # 文件监控
    "file_monitor": [
        "check_directory_status", "get_new_files", "mark_cleanup_done",
    ],
    # 变量管理
    "variable": [
        "set_variable", "get_variable", "list_variables",
    ],
}

# 反向索引：工具名 → 类别名
_TOOL_TO_CATEGORY: dict = {}
for _cat, _tools in TOOL_CATEGORIES.items():
    for _t in _tools:
        _TOOL_TO_CATEGORY[_t] = _cat


def get_tool_category(tool_name: str) -> str:
    """获取工具所属的方法类别。未知工具返回 'unknown'。"""
    return _TOOL_TO_CATEGORY.get(tool_name, "unknown")


# 同类失败时的策略提示（注入 system prompt 让 LLM 换方案）
CATEGORY_FAILURE_HINTS = {
    "dom_interact": (
        "[提示] DOM 交互类工具连续失败。对于动态网站（B站、YouTube 等），"
        "优先从 page_text / ab_get_text 提取关键信息（如 BV 号、视频 ID），"
        "然后直接构造 URL 访问，而不是尝试点击页面元素。"
    ),
    "dom_observe": (
        "[提示] 页面观察类工具连续失败。页面可能未正确加载，"
        "尝试 ab_open 重新打开，或换用 web_search 获取信息。"
    ),
    "url_navigate": (
        "[提示] URL 导航类工具连续失败。检查 URL 是否正确，"
        "或尝试用 web_search 搜索后再访问。"
    ),
    "file_ops": (
        "[提示] 文件操作连续失败。检查路径是否存在、权限是否足够，"
        "或尝试用 run_command 执行 ls/dir 确认目录结构。"
    ),
    "command": (
        "[提示] 命令执行连续失败。检查命令语法和工作目录，"
        "或尝试拆分为更简单的命令。"
    ),
}
