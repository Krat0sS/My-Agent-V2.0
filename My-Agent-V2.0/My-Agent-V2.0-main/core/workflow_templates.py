# -*- coding: utf-8 -*-
"""
工作流模板引擎 — 零成本确定性步骤生成

匹配策略：用户输入 → 模板匹配 → 直接生成 steps → WorkflowRunner
未命中 → 回退到 LLM planner

模板来源：
1. 内置模板（高频场景硬编码）
2. 沉淀模板（从成功的 workflow 中自动学习）
"""
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from core.workflow import WorkflowStep


# ═══════════════════════════════════════════════════════════
# 模板数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class WorkflowTemplate:
    """工作流模板"""
    name: str                           # 模板名
    pattern: str                        # 匹配模式（正则）
    description: str                    # 描述
    steps: List[Dict[str, Any]]         # 步骤定义（含 {变量} 占位符）
    variables: List[str] = field(default_factory=list)  # 自动从 pattern 中提取
    tags: List[str] = field(default_factory=list)        # 标签（用于分类）
    source: str = "builtin"             # builtin / learned
    use_count: int = 0                  # 使用次数
    success_count: int = 0              # 成功次数
    created_at: float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float:
        return self.success_count / self.use_count if self.use_count > 0 else 0.0


# ═══════════════════════════════════════════════════════════
# 内置模板库
# ═══════════════════════════════════════════════════════════

BUILTIN_TEMPLATES = [
    # ── 通讯类：微信发消息（浏览器内操作） ──
    WorkflowTemplate(
        name="wechat_send_message",
        pattern=r"(?:打开|启动|切换到?)?\s*微信\s*(?:给|发给|告诉)\s*(?P<contact>[^\s,，。！!?？]+?)\s*(?:发|说|讲|聊)\s*(?:一条|一条消息|个消息|句话)?\s*(?P<message>.+)",
        description="在浏览器中打开微信网页版给联系人发消息",
        steps=[
            {"tool": "ab_open", "params": {"url": "https://wx.qq.com"}, "action": "打开微信网页版"},
            {"tool": "ab_wait", "params": {"selector": "body", "timeout": 3000}, "action": "等待页面加载"},
            {"tool": "ab_screenshot", "params": {}, "action": "截图查看当前状态"},
        ],
        variables=["contact", "message"],
        tags=["微信", "通讯", "消息", "聊天"],
    ),

    # ── 通讯类：通用发消息 ──
    WorkflowTemplate(
        name="send_message_with_app",
        pattern=r"(?:打开|启动|切换到?)\s*(?P<app>微信|QQ|钉钉|飞书|Telegram|WhatsApp|企业微信)\s*(?:给|发给|告诉)?\s*(?P<contact>.+?)\s*(?:发|说)\s*(?P<message>.+)",
        description="在浏览器中打开应用网页版给联系人发消息",
        steps=[
            {"tool": "ab_screenshot", "params": {}, "action": "截图查看当前状态"},
        ],
        variables=["app", "contact", "message"],
        tags=["通讯", "消息", "应用"],
    ),

    # ── 通讯类：简单发消息（当前页面操作） ──
    WorkflowTemplate(
        name="send_message",
        pattern=r"(?:给|发给|跟|对)\s*(?P<contact>[^\s,，。！!?？]+?)\s*(?:发|说|讲|聊)\s*(?:一条|一条消息|个消息|句话)?\s*(?P<message>.+)",
        description="在当前页面给联系人发消息",
        steps=[
            {"tool": "ab_screenshot", "params": {}, "action": "截图查看当前状态"},
        ],
        variables=["contact", "message"],
        tags=["通讯", "消息", "聊天"],
    ),
    WorkflowTemplate(
        name="tell_someone",
        pattern=r"^(?=.*(告诉|转告|跟他说|帮我跟))(?!.*(分析|反馈|建议|优化|改进|你觉得|你认为|你来看|综合|方案|代码|项目|架构|技术)).{0,100}$",
        description="告诉某人某事",
        steps=[
            {"tool": "ab_screenshot", "params": {}, "action": "截图查看当前状态"},
        ],
        variables=["contact", "message"],
        tags=["通讯", "消息", "聊天"],
    ),

    # ── 文件操作类 ──
    WorkflowTemplate(
        name="organize_files",
        pattern=r"(?:整理|归类|分类|清理)\s*(?P<path>.+?)(?:文件夹?|目录)?\s*(?:里的|下面的|中的)?\s*(?P<file_type>.+?)(?:文件)?",
        description="整理指定目录下的文件",
        steps=[
            {"tool": "scan_files", "params": {"path": "{path}"}, "action": "查看目录内容"},
            {"tool": "organize_directory", "params": {"path": "{path}"}, "action": "整理文件"},
        ],
        variables=["path", "file_type"],
        tags=["文件", "整理"],
    ),
    WorkflowTemplate(
        name="backup_files",
        pattern=r"(?:备份|复制|打包)\s*(?P<source>.+?)\s*(?:到|去|至)\s*(?P<dest>.+)",
        description="备份文件到指定位置",
        steps=[
            {"tool": "scan_files", "params": {"path": "{source}"}, "action": "确认源目录"},
            {"tool": "run_command", "params": {"command": "mkdir -p '{dest}'"}, "action": "创建目标目录"},
            {"tool": "batch_move", "params": {"moves": [{"src": "{source}", "dst": "{dest}"}]}, "action": "复制文件"},
        ],
        variables=["source", "dest"],
        tags=["文件", "备份"],
    ),

    # ── 搜索类 ──
    WorkflowTemplate(
        name="search_and_open",
        pattern=r"(?:搜索|搜|查找|找)\s*(?P<query>.+?)\s*(?:然后|接着|再)?\s*(?:打开|点开|进入)\s*(?:第一个|第一个结果|第一个链接)?",
        description="搜索并打开第一个结果",
        steps=[
            {"tool": "web_search", "params": {"query": "{query}"}, "action": "搜索"},
            {"tool": "ab_open", "params": {"url": "{first_result_url}"}, "action": "打开第一个结果"},
        ],
        variables=["query"],
        tags=["搜索", "浏览器"],
    ),

    # ── 系统操作类 ──
    WorkflowTemplate(
        name="screenshot_and_describe",
        pattern=r"(?:截屏|截图|截个图|看看屏幕|看看当前)(?:然后|并且|再)?\s*(?:描述|分析|说说)?",
        description="截图并描述内容",
        steps=[
            {"tool": "ab_screenshot", "params": {}, "action": "截图"},
            {"tool": "vision_analyze", "params": {}, "action": "描述截图内容"},
        ],
        variables=[],
        tags=["截图", "分析"],
    ),
]


# ═══════════════════════════════════════════════════════════
# 模板匹配引擎
# ═══════════════════════════════════════════════════════════

class TemplateEngine:
    """
    模板匹配引擎。

    用法：
        engine = TemplateEngine()
        match = engine.match("给张三发一条消息说明天开会")
        if match:
            steps = engine.generate_steps(match)
    """

    def __init__(self, learned_path: str = None):
        self.templates: List[WorkflowTemplate] = list(BUILTIN_TEMPLATES)
        self.learned_path = learned_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "learned_templates.json"
        )
        self._load_learned()

    def match(self, user_input: str) -> Optional[Tuple[WorkflowTemplate, Dict[str, str]]]:
        """
        匹配用户输入到模板。

        Returns:
            (template, variables) 或 None
        """
        user_input = user_input.strip()
        if not user_input:
            return None

        best_match = None
        best_score = 0.0

        for tmpl in self.templates:
            try:
                m = re.search(tmpl.pattern, user_input, re.IGNORECASE)
            except re.error:
                continue

            if m:
                variables = m.groupdict()
                # 评分：匹配的变量数 + 模板成功率
                score = len(variables) + tmpl.success_rate * 0.5
                if score > best_score:
                    best_score = score
                    best_match = (tmpl, variables)

        return best_match

    def generate_steps(self, match: Tuple[WorkflowTemplate, Dict[str, str]]) -> List[WorkflowStep]:
        """
        从模板匹配结果生成 WorkflowStep 列表。

        模板中的 {变量} 会被替换为实际值。
        """
        tmpl, variables = match
        steps = []

        for i, step_def in enumerate(tmpl.steps):
            # 替换参数中的变量
            params = {}
            for k, v in step_def.get("params", {}).items():
                if isinstance(v, str):
                    for var_name, var_value in variables.items():
                        v = v.replace(f"{{{var_name}}}", var_value)
                params[k] = v

            # 替换 action 中的变量
            action = step_def.get("action", f"步骤{i+1}")
            for var_name, var_value in variables.items():
                action = action.replace(f"{{{var_name}}}", var_value)

            tool = step_def.get("tool", "auto")
            # 替换 tool 中的变量（理论上不应该有，但以防万一）
            for var_name, var_value in variables.items():
                tool = tool.replace(f"{{{var_name}}}", var_value)

            steps.append(WorkflowStep(
                id=i + 1,
                action=action,
                tool=tool,
                params=params,
                depends_on=[i] if i > 0 else [],  # 默认串行依赖
                risk=step_def.get("risk", "low"),
            ))

        return steps

    def record_result(self, template_name: str, success: bool):
        """记录模板使用结果（用于自动调整排序）"""
        for tmpl in self.templates:
            if tmpl.name == template_name:
                tmpl.use_count += 1
                if success:
                    tmpl.success_count += 1
                break

    def learn_template(self, user_input: str, steps: List[WorkflowStep],
                        goal: str = "", tags: List[str] = None) -> WorkflowTemplate:
        """
        从成功的 workflow 中学习新模板。

        简单实现：用用户输入作为 pattern 的一部分，
        步骤直接复用。后续可以用 LLM 提炼更通用的 pattern。
        """
        # 从用户输入中提取可变部分作为 pattern
        pattern = re.escape(user_input)
        # 将数字替换为 \d+
        pattern = re.sub(r'\\\d+', r'\\d+', pattern)
        # 将引号内容替换为捕获组
        pattern = re.sub(r'\\["\u201c\u201d](.+?)\\["\u201c\u201d]', r'(?P<quote_\1>.+?)', pattern)

        step_dicts = []
        for s in steps:
            step_dicts.append({
                "tool": s.tool,
                "params": s.params,
                "action": s.action,
                "risk": s.risk,
            })

        tmpl = WorkflowTemplate(
            name=f"learned_{int(time.time())}",
            pattern=pattern,
            description=goal or user_input[:50],
            steps=step_dicts,
            tags=tags or ["learned"],
            source="learned",
            use_count=1,
            success_count=1,
        )

        self.templates.append(tmpl)
        self._save_learned()
        return tmpl

    def get_stats(self) -> Dict[str, Any]:
        """获取模板统计"""
        builtin = [t for t in self.templates if t.source == "builtin"]
        learned = [t for t in self.templates if t.source == "learned"]
        return {
            "total": len(self.templates),
            "builtin": len(builtin),
            "learned": len(learned),
            "most_used": sorted(self.templates, key=lambda t: t.use_count, reverse=True)[:5],
        }

    # ── 持久化 ──

    def _load_learned(self):
        """加载已学习的模板"""
        if not os.path.exists(self.learned_path):
            return
        try:
            with open(self.learned_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                tmpl = WorkflowTemplate(
                    name=item["name"],
                    pattern=item["pattern"],
                    description=item.get("description", ""),
                    steps=item.get("steps", []),
                    variables=item.get("variables", []),
                    tags=item.get("tags", []),
                    source="learned",
                    use_count=item.get("use_count", 0),
                    success_count=item.get("success_count", 0),
                    created_at=item.get("created_at", 0),
                )
                self.templates.append(tmpl)
        except (json.JSONDecodeError, KeyError):
            pass

    def _save_learned(self):
        """保存已学习的模板"""
        learned = [t for t in self.templates if t.source == "learned"]
        os.makedirs(os.path.dirname(self.learned_path), exist_ok=True)
        data = []
        for t in learned:
            data.append({
                "name": t.name,
                "pattern": t.pattern,
                "description": t.description,
                "steps": t.steps,
                "variables": t.variables,
                "tags": t.tags,
                "use_count": t.use_count,
                "success_count": t.success_count,
                "created_at": t.created_at,
            })
        with open(self.learned_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════
# Phase 3: 模板执行统计（供 self_optimizer 使用）
# ═══════════════════════════════════════════════════════════

def get_template_execution_stats() -> Dict[str, dict]:
    """
    返回已投用模板的执行统计（至少被使用过 3 次）。
    供 Phase 3 自我优化引擎检测模板误匹配模式。
    """
    engine = get_template_engine()
    stats = {}
    for tmpl in engine.templates:
        total = tmpl.use_count
        if total >= 3:
            stats[tmpl.name] = {
                'total': total,
                'success_count': tmpl.success_count,
                'completion_rate': tmpl.success_count / total if total > 0 else 0
            }
    return stats


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_engine: Optional[TemplateEngine] = None

def get_template_engine() -> TemplateEngine:
    global _engine
    if _engine is None:
        _engine = TemplateEngine()
    return _engine


def try_template(user_input: str) -> Optional[Tuple[WorkflowTemplate, List[WorkflowStep]]]:
    """
    尝试模板匹配。命中返回 (template, steps)，未命中返回 None。
    这是给 conversation.py 调用的入口。
    """
    engine = get_template_engine()
    match = engine.match(user_input)
    if match:
        tmpl, variables = match
        steps = engine.generate_steps(match)
        return tmpl, steps
    return None
