"""
文件监控插件 — check_directory_status / get_new_files / mark_cleanup_done
从 builtin.py 拆分，自注册到 ToolRegistry
"""
import json
from tools.registry import registry
from tools.tool_utils import ToolResult


def _check_directory_status() -> str:
    from tools.file_monitor import check_all
    try:
        result = check_all()
        if result.get("needs_remind", 0) > 0:
            from tools.file_monitor import mark_reminded
            for d in result.get("remind_dirs", []):
                mark_reminded(d.get("dir", ""))
        return ToolResult.ok(result)
    except Exception as e:
        return ToolResult.fail(f"目录状态检查失败: {e}", "E_MONITOR_FAILED",
                               recoverable=True)


registry.register(
    name="check_directory_status",
    description="检查桌面和下载文件夹的文件状态。返回各目录文件数量、大小、是否需要整理。用于心跳检查或主动整理提醒。",
    schema={
        "name": "check_directory_status",
        "description": "检查桌面和下载文件夹的文件状态。",
        "parameters": {"type": "object", "properties": {}}
    },
    handler=_check_directory_status,
    category="file_monitor",
    risk_level="low",
)


def _get_new_files(path: str = None, hours: int = 24) -> str:
    from tools.file_monitor import get_new_files as _get_new
    from tools.tool_utils import get_special_folder
    try:
        if path is None:
            path = get_special_folder("Downloads")
        result = _get_new(path, hours)
        return ToolResult.ok({"path": path, "hours": hours, "new_count": len(result), "files": result})
    except Exception as e:
        return ToolResult.fail(f"获取新文件失败: {e}", "E_MONITOR_FAILED",
                               recoverable=True)


registry.register(
    name="get_new_files",
    description="获取指定目录最近新增的文件（默认 24 小时内）。用于检测新下载的文件并判断是否需要整理。",
    schema={
        "name": "get_new_files",
        "description": "获取指定目录最近新增的文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径"},
                "hours": {"type": "integer", "description": "检查最近多少小时内的新增文件", "default": 24}
            }
        }
    },
    handler=_get_new_files,
    category="file_monitor",
    risk_level="low",
)


def _mark_cleanup_done(dir_label: str) -> str:
    from tools.file_monitor import mark_cleanup
    try:
        mark_cleanup(dir_label)
        return ToolResult.ok({"message": f"已标记「{dir_label}」为已整理，7 天内不再提醒"})
    except Exception as e:
        return ToolResult.fail(f"标记失败: {e}", "E_MONITOR_FAILED",
                               recoverable=True)


registry.register(
    name="mark_cleanup_done",
    description="标记某个目录刚刚整理过。用于重置提醒计时器，避免重复提醒。",
    schema={
        "name": "mark_cleanup_done",
        "description": "标记某个目录刚刚整理过。",
        "parameters": {
            "type": "object",
            "properties": {
                "dir_label": {"type": "string", "description": "目录标签（如 '桌面', '下载'）"}
            },
            "required": ["dir_label"]
        }
    },
    handler=_mark_cleanup_done,
    category="file_monitor",
    risk_level="low",
)
