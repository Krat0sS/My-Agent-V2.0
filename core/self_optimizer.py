# -*- coding: utf-8 -*-
"""
自我优化引擎 (Self-Optimizer)
=============================
Phase 3 核心模块：从执行日志和工具效果表中自动识别重复性问题，
生成安全可执行的优化提案，并静默应用于运行时配置。
纯统计 + 规则驱动，不依赖 LLM。
"""

import json
import os
import datetime
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger("self_optimizer")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class FailurePattern:
    pattern_type: str   # "tool_failure" | "missing_fallback" | "template_mismatch"
    description: str
    evidence: dict
    severity: float     # 0.0 ~ 1.0


@dataclass
class OptimizationProposal:
    action: str         # "add_fallback" | "adjust_availability" | "tighten_pattern"
    target: str
    payload: dict
    auto_apply: bool
    reason: str


# ---------------------------------------------------------------------------
# 模式检测
# ---------------------------------------------------------------------------
def detect_patterns(
    effectiveness,       # GuaToolEffectiveness 实例
    execution_logs: List[Dict],
    templates            # List[WorkflowTemplate]
) -> List[FailurePattern]:
    """
    从近期数据中识别可优化的模式。
    完全基于统计和规则，无 LLM 参与。
    """
    patterns = []

    # ---- 1. 近期高频失败工具 ------------------------------------------------
    recent_stats = effectiveness.get_recent_stats(limit=100)
    for tool, stats in recent_stats.items():
        if stats['total'] >= 5 and stats['fail_rate'] > 0.6:
            patterns.append(FailurePattern(
                pattern_type="tool_failure",
                description=f"工具 [{tool}] 近期失败率 {stats['fail_rate']:.0%}",
                evidence={"tool": tool, "fail_count": stats['fail_count'], "total": stats['total']},
                severity=stats['fail_rate']
            ))

    # ---- 2. 降级链缺失 ------------------------------------------------------
    from tools.registry import registry
    tool_fail_streak: Dict[str, int] = {}

    for log in execution_logs[-50:]:
        tool = log.get('tool_name', '')
        if not tool:
            continue
        success = log.get('success', 0) == 1

        if success:
            tool_fail_streak.pop(tool, None)
        else:
            tool_fail_streak[tool] = tool_fail_streak.get(tool, 0) + 1

    for tool, streak in tool_fail_streak.items():
        if streak >= 3:
            fallbacks = registry.TOOL_FALLBACKS.get(tool, [])
            has_available = any(
                registry.get(fb) and registry.get(fb).is_available()
                for fb in fallbacks
            )
            if not has_available:
                patterns.append(FailurePattern(
                    pattern_type="missing_fallback",
                    description=f"工具 [{tool}] 连续失败 {streak} 次且无可用降级链",
                    evidence={"tool": tool, "streak": streak},
                    severity=0.7
                ))

    # ---- 3. 模板误匹配 ------------------------------------------------------
    from core.workflow_templates import get_template_execution_stats
    tmpl_stats = get_template_execution_stats()
    for tmpl_name, stats in tmpl_stats.items():
        if stats['completion_rate'] < 0.5:
            patterns.append(FailurePattern(
                pattern_type="template_mismatch",
                description=f"模板 [{tmpl_name}] 完成率仅 {stats['completion_rate']:.0%}",
                evidence={"template": tmpl_name, "completion_rate": stats['completion_rate']},
                severity=0.8
            ))

    return patterns


# ---------------------------------------------------------------------------
# 提案生成
# ---------------------------------------------------------------------------
def generate_proposals(patterns: List[FailurePattern]) -> List[OptimizationProposal]:
    """
    将检测到的模式转换为具体的、可验证的优化动作。
    auto_apply=True 的动作仅修改运行时配置（降级表、工具可用性评分），不碰代码。
    """
    proposals = []

    for p in patterns:
        if p.pattern_type == "missing_fallback":
            tool = p.evidence["tool"]
            proposals.append(OptimizationProposal(
                action="add_fallback",
                target=f"registry.TOOL_FALLBACKS",
                payload={"tool": tool, "fallback": "run_command"},
                auto_apply=True,
                reason=f"工具 [{tool}] 多次失败且无降级，自动添加运行命令作为通用回退"
            ))

        elif p.pattern_type == "tool_failure":
            tool = p.evidence["tool"]
            proposals.append(OptimizationProposal(
                action="adjust_availability",
                target=f"registry.tool_availability[{tool}]",
                payload={"tool": tool, "score": 0.2},
                auto_apply=True,
                reason=f"工具 [{tool}] 近期失败率过高，降低可用性评分以避免频繁调用"
            ))

        elif p.pattern_type == "template_mismatch":
            tmpl = p.evidence["template"]
            proposals.append(OptimizationProposal(
                action="tighten_pattern",
                target=f"template:{tmpl}",
                payload={"template": tmpl},
                auto_apply=False,   # 正则修改需人工审核
                reason=f"模板 [{tmpl}] 误匹配率高，建议收紧触发正则"
            ))

    return proposals


# ---------------------------------------------------------------------------
# 安全执行
# ---------------------------------------------------------------------------
def apply_proposals(
    proposals: List[OptimizationProposal],
    registry,
    staging_dir: str = "proposals"
):
    """
    执行提案：自动应用安全项，危险项写入 staging 目录等待人工确认。
    """
    for prop in proposals:
        if prop.auto_apply and prop.action == "add_fallback":
            tool = prop.payload["tool"]
            fallback = prop.payload["fallback"]
            if fallback not in registry.TOOL_FALLBACKS.get(tool, []):
                registry.TOOL_FALLBACKS.setdefault(tool, []).append(fallback)
                logger.info(f"自动添加降级链: {tool} -> {fallback}")

        elif prop.auto_apply and prop.action == "adjust_availability":
            tool = prop.payload.get("tool", "")
            if tool:
                registry.set_availability(tool, prop.payload["score"])
                logger.info(f"自动调整可用性: {tool} → {prop.payload['score']}")

        else:
            # 写入 proposals/ 目录，供人工采纳
            os.makedirs(staging_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{staging_dir}/proposal_{timestamp}_{prop.action}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    "action": prop.action,
                    "target": prop.target,
                    "payload": prop.payload,
                    "reason": prop.reason,
                    "created_at": datetime.datetime.now().isoformat(),
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"生成待审核提案: {filename}")


# ---------------------------------------------------------------------------
# 主循环入口
# ---------------------------------------------------------------------------
async def self_optimization_cycle(
    effectiveness,
    execution_logs: List[Dict],
    templates,
    registry
) -> Optional[List[OptimizationProposal]]:
    """
    执行一次完整的自我优化周期。
    - 从 effectiveness 表和最近的执行日志中提取数据
    - 识别模式 → 生成提案 → 安全执行
    建议在后台异步任务中调用，不阻塞主对话。
    """
    try:
        patterns = detect_patterns(effectiveness, execution_logs, templates)
        if not patterns:
            logger.debug("未发现可优化的模式")
            return None

        logger.info(f"发现 {len(patterns)} 个优化模式: {[p.description for p in patterns]}")
        proposals = generate_proposals(patterns)
        apply_proposals(proposals, registry, staging_dir="proposals")

        return proposals
    except Exception as e:
        logger.error(f"自我优化周期异常: {e}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 查询接口（供 UI 或调试使用）
# ---------------------------------------------------------------------------
def get_recent_optimizations(staging_dir: str = "proposals", limit: int = 5) -> List[dict]:
    """获取最近的优化提案记录"""
    if not os.path.exists(staging_dir):
        return []
    files = sorted(
        [f for f in os.listdir(staging_dir) if f.endswith('.json')],
        reverse=True
    )[:limit]
    results = []
    for fname in files:
        try:
            with open(os.path.join(staging_dir, fname), 'r', encoding='utf-8') as f:
                results.append(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return results
