# -*- coding: utf-8 -*-
"""
技能加载器 — 兼容 YAML frontmatter + 旧格式

新格式：SKILL.md 顶部有 --- 包裹的 YAML 元数据
旧格式：纯 markdown，从 ## 段落提取信息

两种格式都支持，自动检测。
"""

import os
import re
import time
import yaml
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict
import config

logger = logging.getLogger("skill_loader")


@dataclass
class Skill:
    """已加载的技能"""
    name: str
    path: str
    version: str = "1.0"
    description: str = ""
    trigger_keywords: List[str] = field(default_factory=list)
    trigger_exclude: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    steps: List[dict] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    rollback: Optional[str] = None
    raw_md: str = ""
    keywords: List[str] = field(default_factory=list)
    success_rate: float = -1.0  # -1 表示无数据
    total_uses: int = 0
    deprecated: bool = False


def parse_skill_md(content: str) -> dict:
    """解析 YAML frontmatter + markdown body"""
    result = {"frontmatter": {}, "body": content, "sections": {}}

    # 提取 frontmatter
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if match:
        try:
            result["frontmatter"] = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            pass
        result["body"] = content[match.end():]

    # 从 body 提取 ## 段落
    sections = {}
    current_section = None
    current_lines = []
    for line in result["body"].split("\n"):
        m = re.match(r'^##\s+(.+)', line)
        if m:
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    result["sections"] = sections
    return result


def load_skill(skill_dir: Path) -> Optional[Skill]:
    """加载单个技能目录（自动检测新旧格式）"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    content = skill_md.read_text(encoding="utf-8")
    parsed = parse_skill_md(content)
    fm = parsed["frontmatter"]
    sections = parsed["sections"]

    # ═══ 新格式：从 YAML frontmatter 提取 ═══
    if fm:
        name = fm.get("name", skill_dir.name)
        version = fm.get("version", "1.0")
        description = fm.get("description", "")

        trigger = fm.get("trigger", {})
        trigger_keywords = trigger.get("keywords", [])
        trigger_exclude = trigger.get("exclude", [])

        tools = fm.get("tools", [])
        steps_raw = fm.get("steps", [])
        constraints = fm.get("constraints", [])
        rollback = fm.get("rollback")

    # ═══ 旧格式：从 markdown sections 提取 ═══
    else:
        name = skill_dir.name
        version = "1.0"
        description = sections.get("目标", sections.get("Goal", ""))

        # 从目标段落提取关键词
        trigger_keywords = _extract_keywords(description + " " + name)
        trigger_exclude = []

        # 从前置工具段落提取工具列表
        tools_text = sections.get("前置工具", sections.get("Required Tools", ""))
        tools = _extract_tools_list(tools_text)

        # 从执行步骤段落提取步骤
        steps_text = sections.get("执行步骤", sections.get("Steps", ""))
        steps_raw = [
            {"action": line.strip().lstrip("0123456789. ")}
            for line in steps_text.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]

        # 从约束段落提取
        constraints_text = sections.get("约束", sections.get("Constraints", ""))
        constraints = [
            line.strip().lstrip("- •*")
            for line in constraints_text.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        rollback = None

    # ═══ 通用处理 ═══

    # 如果 frontmatter 没有 keywords，从 body 补充
    if not trigger_keywords:
        goal_text = sections.get("目标", sections.get("Goal", ""))
        trigger_keywords = _extract_keywords(goal_text + " " + name)

    # 同义词扩展
    keywords = list(trigger_keywords)
    for part in skill_dir.name.replace("-", " ").replace("_", " ").split():
        if len(part) > 1 and part not in keywords:
            keywords.append(part)

    # 加载 tools.py（自动注册工具）
    tools_py = skill_dir / "tools.py"
    if tools_py.exists():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                f"skills.{skill_dir.name}.tools", tools_py)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"⚠️ 加载技能工具 {skill_dir.name}/tools.py 失败: {e}")

    return Skill(
        name=name, path=str(skill_dir), version=version,
        description=description, trigger_keywords=trigger_keywords,
        trigger_exclude=trigger_exclude, tools=tools, steps=steps_raw,
        constraints=constraints, rollback=rollback, raw_md=content,
        keywords=keywords,
    )


def _extract_keywords(text: str) -> List[str]:
    """从文本提取关键词"""
    try:
        import jieba
        words = list(jieba.cut(text.lower()))
    except ImportError:
        words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', text.lower())
    stopwords = {'的', '了', '是', '在', '有', '和', '与', '或', '等', '被', '把',
                 '从', '到', '对', '中', '上', '下', '不', '也', '都', '就', '还',
                 '我', '你', '他', '她', '它', '们', '这', '那', '帮', '帮我', '请',
                 '一个', '进行', '使用', '通过'}
    return [w.strip() for w in words if len(w.strip()) > 1 and w.strip() not in stopwords]


def _extract_tools_list(text: str) -> List[str]:
    """从前置工具段落提取工具名"""
    tools = []
    for line in text.split("\n"):
        line = line.strip().lstrip("- •*")
        match = re.match(r'^[a-z_][a-z0-9_]*', line)
        if match:
            tools.append(match.group())
        for code in re.findall(r'`([a-z_][a-z0-9_]*)`', line):
            if code not in tools:
                tools.append(code)
    return tools


# ═══ 缓存 ═══

_skills_cache = None
_skills_cache_time = 0
_skills_cache_ttl = 60


def load_all_skills(skills_dir: Path = None) -> List[Skill]:
    """加载所有技能（带缓存）"""
    global _skills_cache, _skills_cache_time
    now = time.time()
    if _skills_cache is not None and (now - _skills_cache_time) < _skills_cache_ttl:
        return _skills_cache

    skill_dirs = []
    if skills_dir is not None:
        skill_dirs.append(skills_dir)
    else:
        # 工作区技能目录
        ws_skills = Path(os.path.join(config.WORKSPACE, "skills"))
        if ws_skills.exists():
            skill_dirs.append(ws_skills)
        # 内置技能目录
        builtin_skills = Path(os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills"))
        if builtin_skills.exists() and builtin_skills != ws_skills:
            skill_dirs.append(builtin_skills)

    skills = []
    seen_names = set()
    for sd in skill_dirs:
        for d in sorted(sd.iterdir()):
            if d.is_dir() and not d.name.startswith(("_", ".")) and d.name != "__pycache__":
                if d.name in seen_names:
                    continue
                try:
                    skill = load_skill(d)
                    if skill:
                        skills.append(skill)
                        seen_names.add(skill.name)
                except Exception as e:
                    print(f"⚠️ 加载技能 {d.name} 失败: {e}")

    _skills_cache = skills
    _skills_cache_time = now

    # 技能淘汰检查：过滤低成功率技能
    _skills_cache = check_skill_deprecation(_skills_cache)

    return _skills_cache


# ═══ 技能淘汰 ═══

_DEPRECATION_THRESHOLD = 0.3  # 成功率低于 30% 标记为 deprecated
_DEPRECATION_MIN_USES = 5     # 至少使用 5 次才判断


def check_skill_deprecation(skills: List[Skill]) -> List[Skill]:
    """检查技能成功率，标记低成功率技能为 deprecated

    Args:
        skills: 技能列表（会原地修改 deprecated 字段）

    Returns:
        过滤后的可用技能列表
    """
    try:
        from yi_framework.effectiveness import ToolEffectiveness
        eff = ToolEffectiveness()
    except ImportError:
        return skills

    available = []
    for skill in skills:
        # 用技能名作为 task_tag 查询效果
        stats = eff.get_tool_stats(skill.name)
        # get_tool_stats 返回的是工具维度，我们需要任务维度
        # 改用直接查询
        try:
            import sqlite3
            conn = sqlite3.connect(eff.db_path)
            row = conn.execute("""
                SELECT COUNT(*), SUM(success)
                FROM tool_effectiveness
                WHERE task_tag = ?
            """, (skill.name,)).fetchone()
            conn.close()

            if row and row[0] >= _DEPRECATION_MIN_USES:
                total = row[0]
                successes = row[1] or 0
                rate = successes / total
                skill.success_rate = round(rate, 3)
                skill.total_uses = total
                if rate < _DEPRECATION_THRESHOLD:
                    skill.deprecated = True
                    logger.info(f"[淘汰] 技能 '{skill.name}' 成功率 {rate:.0%} < {_DEPRECATION_THRESHOLD:.0%}，标记为 deprecated")
        except Exception:
            pass

        if not skill.deprecated:
            available.append(skill)

    return available


def get_skill_prompt_context(skills: List[Skill] = None) -> str:
    """技能摘要（注入 System Prompt）"""
    if skills is None:
        skills = load_all_skills()
    if not skills:
        return ""
    contexts = ["## 已掌握的技能\n"]
    for skill in skills:
        tools_str = ", ".join(skill.tools[:5]) if skill.tools else "无特殊要求"
        contexts.append(f"- **{skill.name}**：{skill.description[:80]}\n  工具：{tools_str}")
    return "\n".join(contexts)
