# -*- coding: utf-8 -*-
"""
技能执行器 — 先推断工具，推断不到才调 LLM

执行流程：
1. 读取 SKILL.md 步骤
2. 每步先用规则推断工具名和参数（0 LLM）
3. 推断不到 → 调 LLM 决定
4. 执行工具 → 记录结果 → 下一步
"""

import json
import re
import asyncio
from typing import Optional, Tuple
from tools.registry import registry
from data import execution_log
import config


# 工具关键词映射（硬编码，0 延迟）
_TOOL_KEYWORDS = {
    'web_search': ['搜索', '搜', '查找', '查', 'search', 'find', 'research'],
    'ab_open': ['打开', '访问', '浏览', 'open', 'visit', '网页'],
    'ab_get_text': ['提取', '获取文本', '内容', 'extract', 'text'],
    'ab_screenshot': ['截图', '截屏', 'screenshot'],
    'read_file': ['读取', '查看文件', 'read', 'cat'],
    'write_file': ['写入', '创建文件', 'write', 'create'],
    'edit_file': ['编辑', '修改文件', 'edit'],
    'scan_files': ['扫描', '列出', 'scan', 'list', '查看目录'],
    'find_files': ['查找文件', '找文件', 'find files'],
    'move_file': ['移动', '搬移', 'move'],
    'run_command': ['执行命令', '运行', 'run', 'execute', 'cmd'],
    'remember': ['记住', '记录', 'remember', '保存记忆'],
    'recall': ['回忆', '想起', 'recall'],
    'git_status': ['git状态', 'git status'],
    'git_diff': ['git差异', 'git diff'],
    'git_add': ['git添加', 'git add'],
    'git_commit': ['git提交', 'git commit'],
    'git_push': ['git推送', 'git push'],
}


class SkillExecutor:
    """技能执行器"""

    def __init__(self, skill, on_progress=None, on_confirm=None, session_id="default"):
        self.skill = skill
        self.on_progress = on_progress
        self.on_confirm = on_confirm
        self.session_id = session_id

    async def execute(self, user_input: str) -> dict:
        """执行技能的所有步骤"""
        results = []
        total_llm_calls = 0
        total_tool_calls = 0

        for i, step in enumerate(self.skill.steps):
            step_text = step if isinstance(step, str) else step.get("action", str(step))

            if self.on_progress:
                self.on_progress(f"  步骤 {i + 1}: {step_text[:50]}...")

            step_result = await self._execute_step(step_text, user_input, i + 1)
            results.append(step_result)
            total_llm_calls += step_result.get("llm_calls", 0)
            total_tool_calls += len(step_result.get("tool_calls", []))

            # 步骤失败则停止
            if not step_result.get("success"):
                if self.on_progress:
                    self.on_progress(f"  ❌ 步骤 {i + 1} 失败，停止执行")
                break

        return {
            "success": all(r.get("success") for r in results),
            "results": results,
            "tool_calls_count": total_tool_calls,
            "llm_calls_count": total_llm_calls,
        }

    async def _execute_step(self, step_text: str, user_input: str, step_num: int) -> dict:
        """单步执行：先推断 → 推断不到调 LLM"""

        # 判断步骤（含逻辑关键词）→ 直接调 LLM
        judgment_keywords = ['检查', '判断', '如果', '则', '否则', '决定', '选择', '汇报', '提示']
        if any(kw in step_text for kw in judgment_keywords):
            return await self._execute_step_via_llm(step_text, user_input, step_num)

        # 第一步：尝试推断工具（0 LLM 调用）
        tool_name, args = self._infer_tool(step_text, user_input)

        if tool_name and registry.get(tool_name):
            # 推断成功 → 直接执行
            try:
                loop = asyncio.get_running_loop()
                result_raw = await loop.run_in_executor(
                    None, registry.execute, tool_name, args, self.session_id, 0.5
                )
            except Exception as e:
                result_raw = json.dumps({"error": True, "message": str(e)})

            success = "error" not in result_raw.lower() and "blocked" not in result_raw.lower()

            # 记录
            execution_log.log_tool_call(
                tool_name, args, result_raw[:500],
                success=success, session_id=self.session_id,
            )

            return {
                "success": success,
                "step": step_num,
                "tool_calls": [{"tool": tool_name, "result": result_raw[:500]}],
                "llm_calls": 0,
                "llm_response": None,
            }

        # 第二步：推断不到 → 调 LLM 决定
        return await self._execute_step_via_llm(step_text, user_input, step_num)

    def _infer_tool(self, step_text: str, user_input: str) -> Tuple[Optional[str], dict]:
        """
        从步骤文本推断工具名和参数（纯规则，0 LLM）

        Returns:
            (tool_name, args) 或 (None, {})
        """
        step_lower = step_text.lower()

        # 1. 从技能的前置工具列表精确匹配
        for tool in self.skill.tools:
            if tool in step_lower:
                return tool, self._default_args(tool, step_text, user_input)

        # 2. 从关键词映射匹配
        for tool, keywords in _TOOL_KEYWORDS.items():
            for kw in keywords:
                if kw in step_lower:
                    # 检查是否在技能工具列表中（如果有列表的话）
                    if self.skill.tools and tool not in self.skill.tools:
                        continue
                    return tool, self._default_args(tool, step_text, user_input)

        return None, {}

    def _default_args(self, tool_name: str, step_text: str, user_input: str) -> dict:
        """根据工具名和上下文推断默认参数"""
        # 搜索类
        if tool_name == "web_search":
            # 从用户输入提取搜索关键词（去掉动作动词）
            query = user_input
            for verb in ['搜索', '搜一下', '查找', '帮我搜', '查一下', '了解']:
                query = query.replace(verb, '').strip()
            return {"query": query} if query else {"query": user_input}

        # 浏览器类
        if tool_name == "ab_open":
            # 从步骤文本提取 URL
            url_match = re.search(r'https?://[^\s\'"]+', step_text)
            if url_match:
                return {"url": url_match.group()}
            # 从用户输入提取
            url_match = re.search(r'https?://[^\s\'"]+', user_input)
            if url_match:
                return {"url": url_match.group()}
            return {}

        if tool_name == "ab_get_text":
            return {"selector": "body"}

        # 文件类
        if tool_name in ("read_file", "write_file", "scan_files", "find_files", "move_file"):
            path_match = re.search(r'[/~][^\s\'"]+', step_text)
            if path_match:
                return {"path": path_match.group()}
            # 从用户输入提取
            path_match = re.search(r'[/~][^\s\'"]+', user_input)
            if path_match:
                return {"path": path_match.group()}
            return {}

        # 命令类
        if tool_name == "run_command":
            cmd_match = re.search(r'`([^`]+)`', step_text)
            if cmd_match:
                return {"command": cmd_match.group(1)}
            return {}

        # 记忆类
        if tool_name == "remember":
            return {"content": user_input}

        return {}

    async def _execute_step_via_llm(self, step_text: str, user_input: str, step_num: int) -> dict:
        """推断不到时，调 LLM 决定工具和参数"""
        from core.llm import chat

        available_tools = registry.get_schemas()
        available_tools = [
            s for s in available_tools
            if registry.get(s["function"]["name"]).is_available()
        ]

        # 限制只暴露技能相关的工具
        if self.skill.tools:
            skill_tools = set(self.skill.tools)
            available_tools = [
                s for s in available_tools
                if s["function"]["name"] in skill_tools
            ]

        prompt = (
            f"当前任务: {user_input}\n"
            f"当前步骤: {step_text}\n\n"
            f"请调用合适的工具完成这个步骤。如果没有合适的工具，直接回复文本结果。"
        )

        messages = [
            {"role": "system", "content": "你是技能执行器。根据步骤描述选择合适的工具并执行。"},
            {"role": "user", "content": prompt},
        ]

        response = await chat(messages, tools=available_tools if available_tools else None)

        if response.get("_error") or response.get("_timeout"):
            return {
                "success": False,
                "step": step_num,
                "tool_calls": [],
                "llm_calls": 1,
                "llm_response": response.get("content", "LLM 调用失败"),
            }

        # 纯文本回复
        if "tool_calls" not in response:
            return {
                "success": True,
                "step": step_num,
                "tool_calls": [],
                "llm_calls": 1,
                "llm_response": response.get("content", ""),
            }

        # 有工具调用 → 执行
        tool_results = []
        for tc in response["tool_calls"]:
            func_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            try:
                loop = asyncio.get_running_loop()
                result_raw = await loop.run_in_executor(
                    None, registry.execute, func_name, args, self.session_id, 0.5
                )
            except Exception as e:
                result_raw = json.dumps({"error": True, "message": str(e)})

            tool_results.append({"tool": func_name, "result": result_raw[:500]})

            execution_log.log_tool_call(
                func_name, args, result_raw[:500],
                success="error" not in result_raw.lower(),
                session_id=self.session_id,
            )

        return {
            "success": all("error" not in r["result"].lower() for r in tool_results),
            "step": step_num,
            "tool_calls": tool_results,
            "llm_calls": 1,
            "llm_response": None,
        }
