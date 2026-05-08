# -*- coding: utf-8 -*-
"""
技能验证器 — 加载时 + 执行前两层检查

v2.2: 防止"命中技能 → 执行失败: 缺少前置工具"的体验断裂

设计原则：
- 加载时检查：前置工具是否存在（缺失 → invalid）
- 执行前检查：工具运行时可用性（可能加载时有，执行时没了）
- 步骤中的工具名：只给警告，不阻断（因为可能是自然语言描述）
"""
import re
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class SkillValidationResult:
    """技能验证结果"""
    skill_name: str
    valid: bool                                  # 前置工具是否都可用
    issues: List[str] = field(default_factory=list)      # 所有问题描述
    missing_tools: List[str] = field(default_factory=list)  # 缺失的前置工具


def validate_skill_at_load(skill) -> SkillValidationResult:
    """
    技能加载时验证。

    检查项：
    1. 前置工具是否在注册表中存在（缺失 → invalid）
    2. 步骤文本中提到的工具名是否可用（仅警告）

    Args:
        skill: Skill 对象（来自 skills/loader.py）

    Returns:
        SkillValidationResult
    """
    from tools.registry import registry
    available = set(registry.get_available_names())

    issues = []
    missing_tools = []

    # 1. 检查前置工具（缺失 → invalid）
    for tool in skill.tools:
        if tool not in available:
            missing_tools.append(tool)
            issues.append(f"前置工具不可用: {tool}")

    # 2. 从步骤文本中提取工具名，只给警告（不阻断）
    # 英文停用词，避免误匹配自然语言
    _stopwords = {
        'auto', 'the', 'a', 'an', 'to', 'if', 'and', 'or', 'not', 'in',
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has',
        'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
        'may', 'might', 'shall', 'can', 'need', 'must', 'that', 'this',
        'for', 'with', 'from', 'by', 'on', 'at', 'of', 'about', 'into',
        'step', 'using', 'via', 'then', 'else', 'true', 'false', 'none',
        'null', 'return', 'result', 'output', 'input', 'data', 'file',
    }
    for step_text in skill.steps:
        # 提取英文标识符（可能是工具名）
        tool_matches = re.findall(r'\b([a-z][a-z0-9_]*)\b', step_text.lower())
        for tool_name in tool_matches:
            if tool_name in _stopwords or tool_name in available:
                continue
            # 可能是工具名，标记为警告
            issues.append(f"步骤中提到的工具可能不可用: {tool_name}")

    return SkillValidationResult(
        skill_name=skill.name,
        valid=len(missing_tools) == 0,
        issues=issues,
        missing_tools=missing_tools,
    )


def validate_skill_before_execute(skill) -> Tuple[bool, str]:
    """
    技能执行前验证（运行时状态可能和加载时不同）。

    Args:
        skill: Skill 对象

    Returns:
        (is_valid, message)
    """
    from tools.registry import registry

    for tool in skill.tools:
        td = registry.get(tool)
        if td is None:
            return False, f"工具 {tool} 已从注册表移除"
        if not td.is_available():
            return False, f"工具 {tool} 当前不可用"

    return True, "ok"
