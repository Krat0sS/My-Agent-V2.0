# -*- coding: utf-8 -*-
"""
子Agent框架 — 上下文隔离 + 工具权限最小化

老师/专家共识：
- 子Agent拥有全新的ConversationManager，不共享主Agent对话历史
- 只暴露允许的工具（allowed_tools），不是全部
- 输出用 [EXTERNAL] 标签包裹，防止 Prompt Injection
- 任务完成后，可自动提炼为 skill.md
"""
import json
import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from core.llm import chat
from tools.registry import registry
from security.context_sanitizer import wrap_external as wrap_external_content


@dataclass
class SubAgentResult:
    """子Agent执行结果"""
    success: bool
    output: str
    tool_calls: List[dict] = field(default_factory=list)
    elapsed_ms: int = 0
    token_cost: int = 0
    error: Optional[str] = None


class SubAgent:
    """
    子Agent — 拥有独立上下文和受限工具集。

    隔离机制：
    1. 上下文隔离：全新的 messages 列表，不继承主Agent历史
    2. 工具权限最小化：只暴露 allowed_tools 中的工具
    3. 输出净化：返回结果用 [EXTERNAL] 标签包裹
    """

    def __init__(self, task: str, allowed_tools: List[str],
                 system_prompt: str = None, parent_session_id: str = "",
                 depth: int = 0, max_depth: int = 2):
        self.task = task
        self.allowed_tools = allowed_tools
        self.parent_session_id = parent_session_id
        self.tool_log: List[dict] = []
        self.depth = depth
        self.max_depth = max_depth

        # 构建隔离的系统提示
        base_prompt = system_prompt or f"你是一个专项子Agent，任务：{task}"
        base_prompt += (
            "\n\n安全规则：你只能使用被授予的工具完成任务。"
            "不要尝试访问未授权的工具。"
            "完成后输出简洁的结果摘要。"
        )
        self.messages = [{"role": "system", "content": base_prompt}]

    def _get_allowed_schemas(self) -> list:
        """只返回被允许的工具 Schema"""
        all_schemas = registry.get_schemas()
        if not self.allowed_tools:
            return []
        return [s for s in all_schemas if s.get("function", {}).get("name", "") in self.allowed_tools]

    async def execute(self, max_rounds: int = 5) -> SubAgentResult:
        """
        执行子Agent任务。

        返回 SubAgentResult，output 已用 [EXTERNAL] 标签包裹。
        """
        # 递归深度保护
        if self.depth >= self.max_depth:
            return SubAgentResult(
                success=False, output="",
                elapsed_ms=0,
                error=f"子Agent递归深度超限 (depth={self.depth}, max={self.max_depth})",
            )

        start = time.time()
        self.messages.append({"role": "user", "content": self.task})

        tool_calls_count = 0
        token_cost = 0
        schemas = self._get_allowed_schemas()

        for round_idx in range(max_rounds):
            try:
                response = await chat(
                    self.messages,
                    tools=schemas if schemas else None,
                    use_ollama=False,
                )
            except Exception as e:
                return SubAgentResult(
                    success=False, output="",
                    elapsed_ms=int((time.time() - start) * 1000),
                    error=f"LLM 调用失败: {str(e)}",
                )

            if response.get("_usage"):
                token_cost += response["_usage"].get("total_tokens", 0)

            if response.get("_error") or response.get("_timeout"):
                return SubAgentResult(
                    success=False, output=response.get("content", ""),
                    elapsed_ms=int((time.time() - start) * 1000),
                    token_cost=token_cost,
                    error="LLM 超时或错误",
                )

            # 没有工具调用 → 最终回复
            if "tool_calls" not in response:
                raw_output = response.get("content", "")
                # 输出净化：用 [EXTERNAL] 标签包裹
                safe_output = wrap_external_content(raw_output)
                return SubAgentResult(
                    success=True, output=safe_output,
                    tool_calls=self.tool_log,
                    elapsed_ms=int((time.time() - start) * 1000),
                    token_cost=token_cost,
                )

            # 执行工具调用
            self.messages.append(response)
            tool_calls_count += 1

            for tc in response["tool_calls"]:
                func_name = tc["function"]["name"]

                # 权限检查：不在允许列表中的工具
                if func_name not in self.allowed_tools:
                    error_msg = json.dumps({
                        "error": True,
                        "message": f"子Agent无权使用工具 {func_name}，允许的工具: {self.allowed_tools}"
                    }, ensure_ascii=False)
                    self.messages.append({
                        "role": "tool", "tool_call_id": tc["id"],
                        "content": error_msg,
                    })
                    self.tool_log.append({
                        "tool": func_name, "denied": True,
                        "reason": "权限不足",
                    })
                    continue

                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                # 执行工具
                try:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, registry.execute, func_name, args
                        ),
                        timeout=30,
                    )
                except asyncio.TimeoutError:
                    result = json.dumps({"error": True, "message": f"工具 {func_name} 超时"})
                except Exception as e:
                    result = json.dumps({"error": True, "message": f"工具 {func_name} 失败: {str(e)}"})

                self.messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "content": result[:2000],  # 截断防止上下文爆炸
                })
                self.tool_log.append({
                    "tool": func_name, "args": args,
                    "success": "error" not in str(result).lower(),
                })

        # 超过最大轮次
        return SubAgentResult(
            success=False, output="子Agent超过最大执行轮次",
            tool_calls=self.tool_log,
            elapsed_ms=int((time.time() - start) * 1000),
            token_cost=token_cost,
            error="超过最大轮次",
        )


@dataclass
class OrchestrationPlan:
    """编排计划：多个子任务"""
    goal: str
    sub_tasks: List[dict]  # [{"task": str, "tools": [str], "depends_on": [int]}]
    parallel: bool = True  # 是否可并行


class Orchestrator:
    """
    编排器 — 管理多个子Agent并行/串行协作。

    职责：
    1. 接收编排计划，创建子Agent
    2. 管理依赖关系（串行/并行）
    3. 汇总所有子Agent结果
    4. 可选：将成功路径提炼为 skill.md
    """

    def __init__(self, parent_session_id: str = "", on_progress=None):
        self.parent_session_id = parent_session_id
        self.on_progress = on_progress
        self.results: List[SubAgentResult] = []

    async def execute_plan(self, plan: OrchestrationPlan) -> dict:
        """
        执行编排计划。

        返回: {"success": bool, "results": [SubAgentResult], "summary": str}
        """
        start = time.time()
        self.results = []

        if plan.parallel:
            # 并行执行（无依赖的子任务同时跑）
            tasks_with_idx = []
            for i, sub in enumerate(plan.sub_tasks):
                if not sub.get("depends_on"):
                    tasks_with_idx.append((i, sub))

            if tasks_with_idx:
                coros = [
                    self._run_sub_agent(sub["task"], sub.get("tools", []))
                    for _, sub in tasks_with_idx
                ]
                parallel_results = await asyncio.gather(*coros, return_exceptions=True)
                for idx, result in zip([i for i, _ in tasks_with_idx], parallel_results):
                    if isinstance(result, Exception):
                        result = SubAgentResult(
                            success=False, output="",
                            error=str(result),
                        )
                    self.results.append(result)
                    # 用占位符填充，保持索引对齐
                    while len(self.results) <= idx:
                        self.results.append(result)

        # 串行执行（有依赖的子任务）
        for i, sub in enumerate(plan.sub_tasks):
            if sub.get("depends_on"):
                # 检查依赖是否都已完成
                deps = sub["depends_on"]
                deps_ok = all(
                    d < len(self.results) and self.results[d].success
                    for d in deps
                )
                if not deps_ok:
                    self.results.append(SubAgentResult(
                        success=False, output="",
                        error=f"依赖任务未成功完成: {deps}",
                    ))
                    continue

                # 将依赖结果注入任务描述
                enriched_task = sub["task"]
                for d in deps:
                    if d < len(self.results) and self.results[d].success:
                        enriched_task += f"\n\n前置结果:\n{self.results[d].output[:500]}"

                result = await self._run_sub_agent(enriched_task, sub.get("tools", []))
                self.results.append(result)

        # 汇总
        elapsed_ms = int((time.time() - start) * 1000)
        all_success = all(r.success for r in self.results)
        summary = self._build_summary()

        return {
            "success": all_success,
            "results": self.results,
            "summary": summary,
            "elapsed_ms": elapsed_ms,
        }

    async def _run_sub_agent(self, task: str, allowed_tools: List[str]) -> SubAgentResult:
        """创建并执行一个子Agent"""
        agent = SubAgent(
            task=task,
            allowed_tools=allowed_tools,
            parent_session_id=self.parent_session_id,
        )

        if self.on_progress:
            self.on_progress(f"🤖 子Agent启动: {task[:50]}... (工具: {len(allowed_tools)}个)")

        result = await agent.execute()

        if self.on_progress:
            status = "✅" if result.success else "❌"
            self.on_progress(f"{status} 子Agent完成: {task[:50]} ({result.elapsed_ms}ms)")

        return result

    def _build_summary(self) -> str:
        """汇总所有子Agent结果"""
        parts = []
        for i, r in enumerate(self.results):
            status = "✅" if r.success else "❌"
            parts.append(f"{status} 任务{i+1}: {r.output[:200]}")
        return "\n".join(parts)


async def generate_skill_from_orchestration(
    user_input: str, plan: OrchestrationPlan,
    results: dict, session_id: str = ""
) -> Optional[str]:
    """
    从成功的多Agent协作中提炼 skill.md。

    老师/专家共识：子Agent完成任务后，自动提炼成功的执行路径为新技能。
    """
    if not results.get("success"):
        return None

    # 构建提炼提示
    steps_summary = []
    for i, (sub, result) in enumerate(zip(plan.sub_tasks, results.get("results", []))):
        if result.success:
            steps_summary.append({
                "step": i + 1,
                "task": sub["task"],
                "tools": sub.get("tools", []),
                "output_preview": result.output[:200],
            })

    if len(steps_summary) < 2:
        return None  # 太简单，不需要沉淀为技能

    from core.intent_router import generate_skill_md, save_skill

    plan_dict = {
        "goal": plan.goal,
        "steps": [
            {"id": s["step"], "action": s["task"], "tool": ",".join(s["tools"]), "depends_on": []}
            for s in steps_summary
        ],
    }

    skill_md = await generate_skill_md(user_input, plan_dict, [])
    if skill_md:
        # 从 plan.goal 生成技能名
        import re
        skill_name = re.sub(r'[^\w\u4e00-\u9fff]+', '-', plan.goal)[:30].strip('-').lower()
        if not skill_name:
            skill_name = f"auto-skill-{int(time.time())}"
        save_skill(skill_name, skill_md)
        return skill_name

    return None
