"""
工具管理器 — 工具启用/禁用/搜索/分类

封装 tools/registry.py，给 UI 层提供统一接口。
"""
import json
from typing import Optional


class ToolManager:
    """工具管理器"""

    def __init__(self, registry=None):
        if registry is None:
            from tools.registry import registry as _reg
            registry = _reg
        self.registry = registry

    def list_by_category(self, available_only: bool = True) -> dict:
        """按分类分组列出工具

        Args:
            available_only: True 时只返回实际可用的工具（默认）
        """
        categories = {}
        for td in self.registry.get_all():
            if available_only and not td.is_available():
                continue
            cat = td.category or "其他"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append({
                "name": td.name,
                "description": td.description,
                "enabled": td.is_available(),
                "risk_level": td.risk_level,
                "manually_overridden": td.is_manually_overridden,
            })
        for cat in categories:
            categories[cat].sort(key=lambda x: x["name"])
        return {"success": True, "categories": categories}

    def search(self, keyword: str, available_only: bool = True) -> dict:
        """按名称或描述搜索工具

        Args:
            keyword: 搜索关键词
            available_only: True 时只搜索可用工具（默认）
        """
        keyword_lower = keyword.lower()
        results = []
        for td in self.registry.get_all():
            if available_only and not td.is_available():
                continue
            if (keyword_lower in td.name.lower() or
                    (td.description and keyword_lower in td.description.lower())):
                results.append({
                    "name": td.name,
                    "description": td.description,
                    "enabled": td.is_available(),
                    "category": td.category,
                    "risk_level": td.risk_level,
                })
        results.sort(key=lambda x: x["name"])
        return {"success": True, "tools": results, "count": len(results)}

    def get(self, tool_name: str) -> dict:
        """获取单个工具详情"""
        td = self.registry.get(tool_name)
        if not td:
            return {"success": False, "error": f"工具不存在: {tool_name}"}
        return {
            "success": True,
            "tool": {
                "name": td.name,
                "description": td.description,
                "schema": td.schema,
                "category": td.category,
                "risk_level": td.risk_level,
                "enabled": td.is_available(),
                "manually_overridden": td.is_manually_overridden,
                "is_async": td.is_async,
            }
        }

    def toggle(self, tool_name: str, enabled: bool) -> dict:
        """启用/禁用单个工具"""
        td = self.registry.get(tool_name)
        if not td:
            return {"success": False, "error": f"工具不存在: {tool_name}"}
        if enabled:
            td.enable()
        else:
            td.disable()
        return {"success": True, "name": tool_name, "enabled": enabled}

    def batch_toggle(self, tool_names: list, enabled: bool) -> dict:
        """批量启用/禁用工具"""
        results = []
        for name in tool_names:
            r = self.toggle(name, enabled)
            results.append(r)
        succeeded = sum(1 for r in results if r.get("success"))
        return {"success": True, "total": len(tool_names), "succeeded": succeeded, "results": results}

    def reset(self, tool_name: str) -> dict:
        """恢复工具为自动检测状态"""
        td = self.registry.get(tool_name)
        if not td:
            return {"success": False, "error": f"工具不存在: {tool_name}"}
        td.reset_manual()
        return {"success": True, "name": tool_name, "enabled": td.is_available()}

    def get_stats(self) -> dict:
        """获取工具统计"""
        all_tools = self.registry.get_all()
        available = [td for td in all_tools if td.is_available()]
        manually_on = [td for td in all_tools if td._manual_enabled is True]
        manually_off = [td for td in all_tools if td._manual_enabled is False]
        by_risk = {}
        for td in all_tools:
            by_risk.setdefault(td.risk_level, 0)
            by_risk[td.risk_level] += 1
        return {
            "success": True,
            "total": len(all_tools),
            "available": len(available),
            "manually_enabled": len(manually_on),
            "manually_disabled": len(manually_off),
            "by_risk": by_risk,
        }

    def auto_configure(self) -> dict:
        """一键自动配置：根据 execution_log 中的调用频率推荐开关"""
        recent = {}
        try:
            from data.execution_log import get_recent_tool_calls
            calls = get_recent_tool_calls(limit=200)
            for call in calls:
                name = call.get('tool_name', '')
                if name:
                    recent[name] = recent.get(name, 0) + 1
        except Exception:
            pass

        all_tools = self.registry.get_all()
        keep_enabled = []
        suggest_disable = []

        for td in all_tools:
            usage_count = recent.get(td.name, 0)
            if usage_count > 0:
                keep_enabled.append(td.name)
            elif td.risk_level == "high":
                suggest_disable.append(td.name)

        return {
            "success": True,
            "keep_enabled": keep_enabled,
            "suggest_disable": suggest_disable,
            "total": len(all_tools),
        }
