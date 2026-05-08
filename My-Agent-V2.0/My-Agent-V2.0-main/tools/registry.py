"""
工具注册表 — 自动发现 + 动态注册 + 优雅降级

替代 builtin.py 中的字典式注册，实现：
- ToolRegistry 单例（线程安全）
- ToolDefinition 数据类
- 自动扫描 tools/ 目录，发现含 registry.register() 的模块
- 动态 Schema：只暴露当前环境实际可用的工具
- check_fn 依赖检查 + TTL 缓存

设计参考：Hermes Agent 的 tools/registry.py
"""
import os
import importlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
import json
from urllib.parse import quote


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    schema: dict                    # OpenAI function calling 格式
    handler: Callable               # async 或 sync 的处理函数
    category: str = "general"       # 工具分类
    check_fn: Optional[Callable] = None  # 依赖检查函数，返回 bool
    is_async: bool = False          # handler 是否是 async
    risk_level: str = "low"         # low / medium / high
    platform: str = "any"           # 运行平台: "windows" / "linux" / "android" / "any"
    availability_score: float = 1.0  # Phase 3: 动态可用性评分（0.0~1.0），仅影响排序
    _available: Optional[bool] = field(default=None, repr=False)
    _check_ts: float = field(default=0.0, repr=False)
    _manual_enabled: Optional[bool] = field(default=None, repr=False)  # 手动开关

    CHECK_TTL = 30  # check_fn 结果缓存秒数

    def is_available(self) -> bool:
        """检查工具是否可用（带 TTL 缓存 + 手动开关）"""
        # 手动开关优先
        if self._manual_enabled is not None:
            return self._manual_enabled
        if self.check_fn is None:
            return True
        now = time.time()
        if self._available is not None and (now - self._check_ts) < self.CHECK_TTL:
            return self._available
        try:
            self._available = bool(self.check_fn())
        except Exception:
            self._available = False
        self._check_ts = now
        return self._available

    def enable(self):
        """手动启用工具"""
        self._manual_enabled = True

    def disable(self):
        """手动禁用工具"""
        self._manual_enabled = False

    def reset_manual(self):
        """恢复自动检测（取消手动开关）"""
        self._manual_enabled = None

    @property
    def is_manually_overridden(self) -> bool:
        """是否被手动开关覆盖"""
        return self._manual_enabled is not None


class ToolRegistry:
    """工具注册表（线程安全单例）"""

    # v2.1: 工具降级链 — 当工具失败/不可用时自动切换备选
    TOOL_FALLBACKS = {
        'web_search': ['ab_open'],
        'ab_open': ['run_command'],
    }

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._lock = threading.Lock()
        self._generation = 0  # 缓存失效计数器
        self._platform_filter: Optional[Callable[[str], bool]] = None  # 平台过滤回调

    def register(self, name: str = None, description: str = "",
                 schema: dict = None, handler: Callable = None,
                 category: str = "general", check_fn: Callable = None,
                 is_async: bool = False, risk_level: str = "low",
                 platform: str = "any",
                 tool_def: ToolDefinition = None) -> ToolDefinition:
        """
        注册工具。两种用法：

        1. 直接传参：
           registry.register(name="web_search", description="...", schema={...}, handler=fn)

        2. 传入 ToolDefinition：
           registry.register(tool_def=ToolDefinition(...))
        """
        if tool_def is not None:
            td = tool_def
        else:
            if not name or handler is None:
                raise ValueError("必须提供 name 和 handler")
            td = ToolDefinition(
                name=name,
                description=description or "",
                schema=schema or {},
                handler=handler,
                category=category,
                check_fn=check_fn,
                is_async=is_async,
                risk_level=risk_level,
                platform=platform,
            )
        with self._lock:
            self._tools[td.name] = td
            self._generation += 1
        return td

    def unregister(self, name: str):
        """注销工具"""
        with self._lock:
            self._tools.pop(name, None)
            self._generation += 1

    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        with self._lock:
            return self._tools.get(name)

    def get_all(self) -> List[ToolDefinition]:
        """获取所有已注册工具"""
        with self._lock:
            return list(self._tools.values())

    def get_available(self) -> List[ToolDefinition]:
        """获取所有当前环境可用的工具（含平台过滤）"""
        with self._lock:
            tools = [td for td in self._tools.values() if td.is_available()]
        # 平台过滤
        if self._platform_filter:
            tools = [td for td in tools if self._platform_filter(td.platform)]
        return tools

    def set_platform_filter(self, filter_fn: Optional[Callable[[str], bool]]):
        """设置平台过滤回调

        Args:
            filter_fn: 接收工具的 platform 字段，返回 True 表示可用
                       None 表示清除过滤（所有平台可用）
        """
        self._platform_filter = filter_fn

    def set_availability(self, tool_name: str, score: float):
        """
        Phase 3: 动态调整工具的可用性评分（0.0~1.0）。
        不影响 is_available() 的结果，仅影响 get_best_tool_for_task 的排序权重。
        """
        td = self.get(tool_name)
        if td:
            td.availability_score = max(0.0, min(1.0, score))

    def get_schemas(self) -> List[dict]:
        """
        获取所有可用工具的 OpenAI function calling schema。
        这是传给 LLM 的工具列表 —— 只包含当前环境实际可用的工具。
        """
        available = self.get_available()
        return [
            {"type": "function", "function": td.schema}
            for td in available
        ]

    def get_names(self) -> List[str]:
        """获取所有已注册工具名"""
        with self._lock:
            return list(self._tools.keys())

    def get_available_names(self) -> List[str]:
        """获取所有可用工具名"""
        return [td.name for td in self.get_available()]

    def count(self) -> int:
        with self._lock:
            return len(self._tools)

    def available_count(self) -> int:
        return len(self.get_available())

    @property
    def generation(self) -> int:
        return self._generation

    def list_by_category(self) -> Dict[str, List[str]]:
        """按分类列出工具"""
        result = {}
        for td in self.get_available():
            result.setdefault(td.category, []).append(td.name)
        return result

    def execute(self, name: str, arguments: dict, session_id: str = "default",
                risk_tolerance: float = 1.0) -> str:
        """
        执行工具调用。
        返回 JSON 字符串结果。

        v2.1: 工具降级 — 失败时自动尝试 TOOL_FALLBACKS 中的备选工具

        Args:
            risk_tolerance: 风险容忍度 0.0~1.0，来自 ExecutionProfile
                           低于阈值时，高风险工具需要确认或被阻止
        """
        td = self.get(name)
        if td is None:
            # v2.1: 工具不存在时尝试降级
            fallback = self._try_fallback(name, arguments, session_id, risk_tolerance)
            if fallback is not None:
                return fallback
            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
        if not td.is_available():
            # v2.1: 工具不可用时尝试降级
            fallback = self._try_fallback(name, arguments, session_id, risk_tolerance)
            if fallback is not None:
                return fallback
            return json.dumps({"error": f"工具不可用: {name}"}, ensure_ascii=False)

        # ═══ 风险容忍度检查 — 已禁用，全部放行 ═══

        # ═══ 安全拦截：接入 FileSystemGuard ═══
        try:
            from security.filesystem_guard import guard
            safety = guard.check_tool_call(name, arguments, session_id=session_id)
            if not safety.safe:
                return json.dumps(
                    {
                        "blocked": True,
                        "reason": safety.reason,
                        "tool": name,
                        "risk_level": safety.risk_level,
                    },
                    ensure_ascii=False,
                )
            if safety.needs_confirm:
                return json.dumps(
                    {
                        "needs_confirm": True,
                        "command": arguments.get("command", ""),
                        "reason": safety.reason,
                    },
                    ensure_ascii=False,
                )
        except ImportError:
            pass  # 安全模块不存在时降级放行（开发环境）

        # ═══ 缓存查询（只读工具） ═══
        try:
            from tools.tool_utils import CACHEABLE_TOOLS, cache_get, cache_set
            if name in CACHEABLE_TOOLS:
                cached = cache_get(name, arguments)
                if cached is not None:
                    return cached
        except ImportError:
            cache_set = None

        # 正常执行工具
        try:
            result = td.handler(**arguments)
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)

            # v2.1: 执行结果为错误时尝试降级（兼容新旧格式）
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    is_error = (parsed.get("error") or
                                parsed.get("success") is False or
                                parsed.get("blocked"))
                    if is_error:
                        fallback = self._try_fallback(name, arguments, session_id, risk_tolerance)
                        if fallback is not None:
                            return fallback
            except (json.JSONDecodeError, TypeError):
                pass

            # 写入缓存（只读工具 + 无错误）
            if name in CACHEABLE_TOOLS and cache_set is not None:
                try:
                    parsed = json.loads(result)
                    if not (isinstance(parsed, dict) and "error" in parsed):
                        cache_set(name, arguments, result)
                except (json.JSONDecodeError, TypeError):
                    pass

            return result
        except Exception as e:
            # v2.1: 异常时尝试降级
            fallback = self._try_fallback(name, arguments, session_id, risk_tolerance)
            if fallback is not None:
                return fallback
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def _try_fallback(self, failed_tool: str, arguments: dict,
                      session_id: str, risk_tolerance: float) -> Optional[str]:
        """尝试降级工具链，复用 execute() 保留安全检查"""
        fallbacks = self.TOOL_FALLBACKS.get(failed_tool, [])
        for fb_name in fallbacks:
            fb_td = self.get(fb_name)
            if not fb_td or not fb_td.is_available():
                continue

            fb_args = self._adapt_args(failed_tool, fb_name, arguments)
            # 用 execute() 递归，保留全部安全门控（风险检查、白名单、熔断）
            result = self.execute(fb_name, fb_args, session_id, risk_tolerance)

            # 检查降级结果是否成功
            try:
                parsed = json.loads(result) if isinstance(result, str) else result
                if isinstance(parsed, dict):
                    if parsed.get("error") or parsed.get("blocked"):
                        continue  # 降级工具也失败了，试下一个
            except (json.JSONDecodeError, TypeError):
                pass

            return result  # 降级成功

        return None

    def _adapt_args(self, from_tool: str, to_tool: str, args: dict) -> dict:
        """降级时的参数适配，含 URL 编码"""
        # web_search → ab_open: 需要把 query 拼成 URL
        if from_tool == "web_search" and to_tool == "ab_open":
            query = args.get("query", "")
            return {"url": f"https://www.bing.com/search?q={quote(query)}"}
        return args

    def get_best_tool_for_task(self, candidate_tools: List[str],
                               hexagram: str = None,
                               prefer_recent: bool = True) -> str:
        """
        从候选工具中根据历史经验选择最佳工具。
        如果无历史数据，返回第一个候选。

        v2.2: 经验回流闭环 — 让工具选择有"记忆"
        """
        if not candidate_tools:
            return "auto"
        if len(candidate_tools) == 1:
            return candidate_tools[0]

        # 尝试从 effectiveness 表获取排序
        try:
            from yi_framework.effectiveness import GuaToolEffectiveness
            eff = GuaToolEffectiveness()
            if hexagram:
                scored = eff.query_best_tools_v2(
                    hexagram=hexagram,
                    candidate_tools=candidate_tools,
                    limit=len(candidate_tools),
                    short_weight=0.7 if prefer_recent else 0.5,
                )
                if scored and scored[0].total_uses > 0:
                    import logging
                    logging.getLogger("registry").info(
                        f"经验选择: {scored[0].tool_name} "
                        f"(成功率 {scored[0].success_rate:.2f}, "
                        f"使用 {scored[0].total_uses} 次)"
                    )
                    return scored[0].tool_name
        except ImportError:
            pass
        except Exception:
            pass

        # 无数据，返回第一个候选
        return candidate_tools[0]


# ═══ 全局单例 ═══
registry = ToolRegistry()


def discover_tools(tools_dir: Path = None):
    """
    自动扫描 tools/ 目录，导入所有含 registry.register() 的模块。
    在 main.py 启动时调用一次即可。
    """
    if tools_dir is None:
        tools_dir = Path(__file__).parent

    for f in sorted(tools_dir.rglob("*.py")):
        if f.name in ("__init__.py", "registry.py"):
            continue
        # 跳过 tests 目录
        if "tests" in f.parts or "test_" in f.name:
            continue
        # 构造模块名：tools/plugins/ocr_locator.py → tools.plugins.ocr_locator
        rel = f.relative_to(tools_dir.parent)
        mod_name = str(rel.with_suffix("")).replace(os.sep, ".").replace("/", ".")
        try:
            importlib.import_module(mod_name)
        except Exception as e:
            print(f"⚠️ 加载工具模块 {mod_name} 失败: {e}")
