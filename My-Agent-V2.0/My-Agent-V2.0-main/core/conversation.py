# -*- coding: utf-8 -*-
"""
对话管理器 — Agent 核心循环（My-Agent 2.0）

单脑决策：route() 是唯一决策入口
四路径分发：技能 → 模板 → 分解 → 纯对话
"""

import json
import os
import re
import time
import datetime
import asyncio
import atexit
import logging
from typing import Callable, Optional, List

logger = logging.getLogger("conversation")
from core.llm import chat
from tools.registry import registry
from tools.tool_utils import get_tool_category, CATEGORY_FAILURE_HINTS
from memory.memory_system import MemorySystem
from security.context_sanitizer import get_security_prompt
from data import execution_log
import config


class Conversation:
    """一次对话会话"""

    def __init__(self, session_id: str = "default", restore: bool = True,
                 on_confirm: Optional[Callable[[str], bool]] = None):
        self.session_id = session_id
        self.memory = MemorySystem()
        self.messages: list[dict] = []
        self.tool_call_count = 0
        self.tool_log: list[dict] = []
        self._browser_session = None
        self._cancel_event = asyncio.Event()
        self._token_usage = []
        self._on_confirm = on_confirm

        # 效果记录器（不再依赖卦象）
        from yi_framework.effectiveness import ToolEffectiveness
        self._effectiveness = ToolEffectiveness()
        self._task_tag = "general"  # 当前任务标签，路由命中时更新

        if restore and self._session_file_exists():
            self._load_session()
        else:
            self._init_system()

    # ═══ 初始化 ═══

    def _init_system(self):
        system_prompt = self.memory.get_system_prompt()
        system_prompt += "\n\n" + get_security_prompt()
        try:
            from skills.loader import get_skill_prompt_context
            skill_context = get_skill_prompt_context()
            if skill_context:
                system_prompt += "\n\n" + skill_context
        except Exception:
            pass
        self.messages = [{"role": "system", "content": system_prompt}]

    @property
    def browser(self):
        return None

    async def cleanup(self):
        self._browser_session = None

    def cancel(self):
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _clear_cancel(self):
        self._cancel_event.clear()

    # ═══ 任务标签生成 ═══

    def _make_task_tag(self, routing, user_message: str) -> str:
        """
        生成任务标签 — 用于效果记录的细粒度维度。

        策略：
        - 技能命中 → skill.name
        - 模板命中 → template.name
        - decompose → 提取关键词
        - direct_tool → complexity
        """
        if routing.matched_skill:
            return routing.matched_skill.name
        if hasattr(routing, 'template_name') and routing.template_name:
            return routing.template_name
        if routing.action == "decompose":
            keywords = self._extract_task_keywords(user_message)
            return f"task:{'-'.join(keywords[:3])}" if keywords else "task:unknown"
        return routing.complexity

    @staticmethod
    def _extract_task_keywords(text: str) -> list:
        """从用户输入提取任务关键词"""
        try:
            import jieba
            words = list(jieba.cut(text.lower()))
        except ImportError:
            words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', text.lower())

        stopwords = {'的', '了', '是', '在', '有', '和', '与', '或', '等', '被', '把',
                     '从', '到', '对', '中', '上', '下', '不', '也', '都', '就', '还',
                     '我', '你', '他', '她', '它', '们', '这', '那', '帮', '帮我', '请'}
        return [w.strip() for w in words if len(w.strip()) > 1 and w.strip() not in stopwords]

    # ═══ 自动记忆提取 ═══

    def _extract_memos(self, text: str) -> list:
        return [m.group(1).strip() for m in re.finditer(r'\[MEMO:\s*(.*?)\]', text, re.DOTALL)
                if m.group(1).strip() and len(m.group(1).strip()) > 2]

    # 触发标签自动提取规则：主题关键词 → 触发词列表
    _TRIGGER_HINTS = {
        "bilibili": ["bilibili", "B站", "视频", "BV号"],
        "youtube": ["youtube", "YouTube", "视频"],
        "github": ["github", "GitHub", "仓库", "clone", "git"],
        "文件整理": ["桌面", "整理", "下载", "文件夹", "文件分类"],
        "搜索": ["搜索", "查找", "搜一下", "搜索引擎"],
        "浏览器": ["浏览器", "网页", "打开网页", "Playwright"],
    }

    def _process_memos(self, text: str) -> int:
        memos = self._extract_memos(text)
        for memo in memos:
            self.memory.save_daily(f"[自动记忆] {memo}")
            pref_keywords = ["喜欢", "偏好", "习惯", "以后", "不要", "总是", "用中文", "简洁", "详细"]
            if any(kw in memo for kw in pref_keywords):
                self.memory.save_file_preference("auto", memo)

            # 自动从记忆内容中提取触发标签
            memo_lower = memo.lower()
            for topic, triggers in self._TRIGGER_HINTS.items():
                if any(t.lower() in memo_lower for t in triggers):
                    self.memory.save_daily(f"[自动记忆] {memo}", triggers=triggers)
                    break
        return len(memos)

    # ═══ 会话持久化 ═══

    def _session_path(self) -> str:
        os.makedirs(config.SESSIONS_DIR, exist_ok=True)
        return os.path.join(config.SESSIONS_DIR, f"{self.session_id}.json")

    def _session_file_exists(self) -> bool:
        return os.path.exists(self._session_path())

    def save_session(self):
        try:
            with open(self._session_path(), "w", encoding="utf-8") as f:
                json.dump({
                    "session_id": self.session_id,
                    "messages": self.messages,
                    "saved_at": datetime.datetime.now().isoformat(),
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_session(self):
        try:
            with open(self._session_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            self.messages = data.get("messages", [])
            if not self.messages:
                self._init_system()
        except Exception:
            self._init_system()

    # ═══ 上下文压缩 ═══

    def _trim_context(self):
        """智能上下文压缩（可配置）"""
        system_msgs = [m for m in self.messages if m["role"] == "system"]
        history = [m for m in self.messages if m["role"] != "system"]

        keep = config.MAX_CONTEXT_TURNS
        if len(history) <= keep:
            return

        # 安全切割：不把 assistant(tool_calls) 和它的 tool 结果分到两边
        cut = len(history) - keep
        while cut > 0 and cut < len(history):
            cur = history[cut]
            prev = history[cut - 1]
            if cur.get("role") == "tool" and prev.get("role") == "assistant" and "tool_calls" in prev:
                cut -= 1
                continue
            break

        old, recent = history[:cut], history[cut:]

        # 压缩 old：user 保留，assistant(tool_calls) → 纯文本摘要，tool → 丢弃
        condensed = []
        for msg in old:
            role = msg.get("role")
            if role == "user":
                condensed.append(msg)
            elif role == "assistant":
                if "tool_calls" in msg:
                    summary = []
                    for tc in msg.get("tool_calls", []):
                        fn = tc.get("function", {})
                        summary.append(f"{fn.get('name', '?')}({fn.get('arguments', '{}')[:60]})")
                    condensed.append({"role": "assistant", "content": f"[调用了: {', '.join(summary)}]"})
                elif msg.get("content"):
                    content = msg["content"]
                    max_len = config.OLD_MSG_MAX_LEN
                    if len(content) > max_len:
                        condensed.append({"role": "assistant",
                            "content": content[:max_len // 2] + "\n...[压缩]...\n" + content[-200:]})
                    else:
                        condensed.append(msg)

        # 确保 recent 不以孤立的 tool 消息开头
        while recent and recent[0]["role"] == "tool":
            recent.pop(0)

        self.messages = system_msgs + condensed + recent

    def _sanitize_messages(self):
        """修复孤儿 tool_call_id — 移除没有对应 tool 结果的 assistant(tool_calls) 条目"""
        tool_call_ids_needed = set()
        tool_call_ids_found = set()
        for msg in self.messages:
            if msg["role"] == "assistant" and "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    tool_call_ids_needed.add(tc["id"])
            if msg["role"] == "tool":
                tool_call_ids_found.add(msg.get("tool_call_id", ""))
                # 截断过大的 base64 内容
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 100000:
                    try:
                        data = json.loads(content)
                        if "base64" in data:
                            data["base64"] = f"[图片已省略，{len(data['base64'])} 字符]"
                            msg["content"] = json.dumps(data, ensure_ascii=False)
                    except (json.JSONDecodeError, TypeError):
                        pass

        missing = tool_call_ids_needed - tool_call_ids_found
        if not missing:
            return

        # 移除包含孤儿 tool_calls 的 assistant 消息（而不是补占位结果）
        # 这样 LLM 不会看到矛盾的信息
        fixed = []
        for msg in self.messages:
            if msg["role"] == "assistant" and "tool_calls" in msg:
                orphan_calls = [tc for tc in msg["tool_calls"] if tc["id"] in missing]
                if orphan_calls:
                    # 保留纯文本内容，丢弃孤儿 tool_calls
                    if msg.get("content"):
                        fixed.append({"role": "assistant", "content": msg["content"]})
                    continue
            fixed.append(msg)
        self.messages = fixed

    # ═══ 工具执行 ═══

    async def _execute_tool(self, func_name: str, args: dict,
                            on_confirm: Optional[Callable[[str], bool]] = None) -> str:
        """工具执行（统一入口）"""
        # ── 权限检查：Web 端工具黑名单 ──
        if hasattr(self, '_web_tool_blacklist') and func_name in self._web_tool_blacklist:
            return json.dumps({
                "blocked": True,
                "reason": f"工具 '{func_name}' 已被用户禁止（权限黑名单）",
                "tool": func_name,
            }, ensure_ascii=False)

        confirm_fn = on_confirm or self._on_confirm
        start_time = time.time()
        loop = asyncio.get_running_loop()

        # GUI 操作确认门控
        browser_tools = {"ab_click", "ab_fill", "ab_type", "ab_press", "ab_screenshot",
                         "ab_open", "ab_dblclick", "ab_hover", "ab_select", "ab_check",
                         "ab_uncheck", "ab_scroll", "ab_scrollintoview", "ab_drag",
                         "ab_wait", "ab_eval", "ab_snapshot_click"}
        subprocess_tools = {"run_command", "run_command_confirmed"}

        if func_name in browser_tools:
            try:
                from security.filesystem_guard import guard
                gui_check = guard.check_gui_operation(func_name, args)
                if gui_check.get("needs_confirm"):
                    if confirm_fn and callable(confirm_fn):
                        if not confirm_fn(gui_check["confirm_message"]):
                            return json.dumps({"cancelled": True, "message": "用户拒绝了桌面操作。"})
                    else:
                        return json.dumps({"blocked": True, "message": f"需要确认: {gui_check['confirm_message']}"})
            except ImportError:
                pass
            result_raw = await self._execute_tool_async(func_name, args)
            return self._log_and_record(func_name, args, result_raw, start_time)

        if func_name in subprocess_tools:
            try:
                from security.filesystem_guard import guard
                safety = guard.check_command(args.get("command", ""))
                if not safety.safe:
                    return self._log_and_record(func_name, args, json.dumps({
                        "blocked": True, "reason": safety.reason, "tool": func_name,
                    }), start_time, success=False)
                if safety.needs_confirm:
                    if confirm_fn and callable(confirm_fn):
                        if not confirm_fn(safety.reason):
                            return self._log_and_record(func_name, args, json.dumps({
                                "cancelled": True, "message": "用户拒绝了命令执行。",
                            }), start_time, success=False)
                    else:
                        return self._log_and_record(func_name, args, json.dumps({
                            "needs_confirm": True, "command": args.get("command", ""),
                            "reason": safety.reason,
                        }), start_time, success=False)
            except ImportError:
                pass

            from tools.subprocess_runner import run_command_async, run_command_confirmed_async
            try:
                if func_name == "run_command":
                    result_raw = await run_command_async(args.get("command", ""), args.get("cwd"), args.get("timeout", 30))
                else:
                    result_raw = await run_command_confirmed_async(args.get("command", ""), args.get("cwd"), args.get("timeout", 30))
            except asyncio.CancelledError:
                result_raw = json.dumps({"cancelled": True, "message": "命令已被取消。"})
            return self._log_and_record(func_name, args, result_raw, start_time)

        # 通用工具执行
        try:
            result_raw = await asyncio.wait_for(
                loop.run_in_executor(None, registry.execute, func_name, args, self.session_id, 0.5),
                timeout=config.TOOL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            result_raw = json.dumps({"error": True, "type": "tool_timeout",
                                     "tool": func_name, "message": f"工具超时 ({config.TOOL_TIMEOUT}s)"})
        except asyncio.CancelledError:
            result_raw = json.dumps({"cancelled": True, "message": "操作已被取消。"})
        except Exception as e:
            result_raw = json.dumps({"error": True, "type": "execution_error",
                                     "tool": func_name, "message": str(e)})

        return self._log_and_record(func_name, args, result_raw, start_time)

    async def _execute_tool_async(self, func_name: str, args: dict) -> str:
        """浏览器工具异步执行"""
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, registry.execute, func_name, args, self.session_id, 0.5),
                timeout=config.TOOL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return json.dumps({"error": True, "message": f"浏览器工具 {func_name} 超时"})
        except Exception as e:
            return json.dumps({"error": True, "message": f"浏览器工具 {func_name} 失败: {str(e)}"})

    def _log_and_record(self, func_name, args, result_raw, start_time, success=None):
        """记录日志 + 效果追踪"""
        elapsed = time.time() - start_time
        if success is None:
            success = "error" not in result_raw.lower() and "blocked" not in result_raw.lower()

        self._log_tool_call(func_name, args, result_raw, elapsed)
        execution_log.log_tool_call(
            func_name, args, result_raw[:500],
            success=success, elapsed_ms=int(elapsed * 1000),
            session_id=self.session_id,
        )

        # 效果记录（用 task_tag 替代 hexagram）
        try:
            self._effectiveness.record(
                task_tag=self._task_tag,
                tool_name=func_name,
                success=success,
                duration_ms=int(elapsed * 1000),
                session_id=self.session_id,
            )
        except Exception:
            pass

        return result_raw

    def _log_tool_call(self, func_name, args, result, elapsed):
        self.tool_log.append({
            "tool": func_name,
            "args": {k: str(v)[:100] for k, v in args.items()},
            "elapsed_ms": int(elapsed * 1000),
            "result_preview": result[:200],
            "timestamp": datetime.datetime.now().isoformat(),
        })

    # ═══════════════════════════════════════════════════════════
    # 主循环：send()
    # ═══════════════════════════════════════════════════════════

    async def send(self, user_message: str,
                   on_confirm: Optional[Callable[[str], bool]] = None,
                   on_progress: Optional[Callable[[str], None]] = None) -> dict:
        """
        主入口 — 单脑决策 + 四路径分发

        路径 A: 技能命中 → SkillExecutor
        路径 B: 模板命中 → WorkflowRunner
        路径 C: 任务分解 → WorkflowRunner / LLM
        路径 D: 纯 LLM 对话（兜底）
        """
        self.messages.append({"role": "user", "content": user_message})
        self.tool_call_count = 0
        self._clear_cancel()
        self._token_usage = []
        rounds = 0
        start_time = time.time()

        self._trim_context()
        self._sanitize_messages()

        # ── 触发记忆注入：根据用户消息中的关键词自动注入相关经验 ──
        triggered = self.memory.get_triggered_memories(user_message)
        if triggered:
            memory_hints = []
            for m in triggered:
                memory_hints.append(f"- [{m['date']}] {m['preview']}")
            memory_text = "\n".join(memory_hints)
            self.messages.append({"role": "system", "content":
                f"[相关记忆]\n以下是与当前话题相关的历史经验，请参考：\n{memory_text}"})
            if on_progress:
                on_progress(f"🧠 已注入 {len(triggered)} 条相关记忆")

        # ═══ 唯一决策入口 ═══
        from core.intent_router import route, decompose_task
        from skills.loader import load_all_skills

        skills = load_all_skills()
        routing = await route(user_message, skills)
        self._task_tag = self._make_task_tag(routing, user_message)

        # 生成推理描述
        complexity_desc = {"simple": "简单指令", "medium": "中等任务", "complex": "复杂任务"}
        action_desc = {
            "direct_tool": "直接调用工具完成，无需任务分解",
            "execute_skill": f"命中已有技能「{routing.matched_skill.name if routing.matched_skill else ''}」，走极速执行路径",
            "decompose": "需要多步分解，正在规划执行步骤",
        }
        reasoning = f"分析用户意图：「{user_message[:50]}」\n复杂度判断：{complexity_desc.get(routing.complexity, routing.complexity)}\n决策：{action_desc.get(routing.action, routing.action)}"

        if on_progress:
            on_progress(f"🎯 理解意图\n{reasoning}")

        # ═══ 路径 A：技能命中 ═══
        if routing.action == "execute_skill" and routing.matched_skill:
            result = await self._path_skill(routing, user_message, on_progress, on_confirm, start_time)
            if result:
                return result

        # ═══ 路径 B：模板命中 ═══
        result = await self._path_template(user_message, on_progress, on_confirm, start_time)
        if result:
            return result

        # ═══ 路径 C：任务分解 ═══
        if routing.action == "decompose":
            result = await self._path_decompose(routing, user_message, on_progress, on_confirm, start_time)
            if result:
                return result

        # ═══ 路径 D：纯 LLM 对话（兜底） ═══
        return await self._path_llm_chat(user_message, on_progress, on_confirm, start_time)

    # ═══ 路径 A：技能执行 ═══

    async def _path_skill(self, routing, user_message, on_progress, on_confirm, start_time):
        """路径 A：技能命中 → SkillExecutor"""
        if on_progress:
            skill = routing.matched_skill
            tools_str = "、".join(skill.tools[:5]) if skill.tools else "无特殊要求"
            on_progress(f"🎯 命中技能「{skill.name}」\n置信度 {routing.match_score:.2f}，技能目标：{skill.description[:60]}\n所需工具：{tools_str}")

        # 验证技能
        try:
            from skills.validator import validate_skill_before_execute
            is_valid, msg = validate_skill_before_execute(routing.matched_skill)
            if not is_valid:
                if on_progress:
                    on_progress(f"⚠️ 技能验证失败: {msg}，回退到任务分解")
                return None  # 回退到后续路径
        except ImportError:
            pass

        from skills.executor import SkillExecutor
        executor = SkillExecutor(
            routing.matched_skill, on_progress=on_progress,
            on_confirm=on_confirm, session_id=self.session_id,
        )
        skill_result = await executor.execute(user_message)

        if skill_result.get("success"):
            response = f"✅ 已通过技能「{routing.matched_skill.name}」完成任务"
            for r in skill_result.get("results", []):
                if r.get("llm_response"):
                    response += f"\n{r['llm_response']}"
            self.messages.append({"role": "assistant", "content": response})
            self.save_session()
            duration_ms = int((time.time() - start_time) * 1000)
            execution_log.log_task(user_input=user_message, matched_skill=routing.matched_skill.name,
                                   match_score=routing.match_score, success=True,
                                   duration_ms=duration_ms, session_id=self.session_id)
            return self._build_result(response, 1)

        if on_progress:
            on_progress(f"⚠️ 技能执行失败，回退到任务分解")
        return None  # 回退

    # ═══ 路径 B：模板匹配 ═══

    async def _path_template(self, user_message, on_progress, on_confirm, start_time):
        """路径 B：模板命中 → WorkflowRunner（零 LLM）"""
        from core.workflow_templates import try_template
        tmpl_hit = try_template(user_message)
        if not tmpl_hit:
            return None

        tmpl, wf_steps = tmpl_hit
        if on_progress:
            on_progress(f"📐 命中模板「{tmpl.description}」\n匹配到预设工作流模板，共 {len(wf_steps)} 个步骤，无需 LLM 推理，直接执行")

        from core.workflow import WorkflowRunner, format_workflow_result
        runner = WorkflowRunner(
            goal=tmpl.description, on_progress=on_progress,
            on_confirm=on_confirm, session_id=self.session_id,
        )
        wf_result = await runner.execute(wf_steps)

        from core.workflow_templates import get_template_engine
        get_template_engine().record_result(tmpl.name, wf_result.success)

        response = format_workflow_result(wf_result)
        self.messages.append({"role": "assistant", "content": response})
        self.save_session()

        duration_ms = int((time.time() - start_time) * 1000)
        execution_log.log_task(user_input=user_message, success=wf_result.success,
                               duration_ms=duration_ms, session_id=self.session_id)
        return self._build_result(response, 1)

    # ═══ 路径 C：任务分解 ═══

    async def _path_decompose(self, routing, user_message, on_progress, on_confirm, start_time):
        """路径 C：任务分解 → WorkflowRunner / LLM"""
        if on_progress:
            on_progress("📝 分析任务结构\n将复杂任务拆解为可执行的子步骤，识别步骤间的依赖关系")

        cached_plan = await decompose_task(user_message)
        if not cached_plan.get("steps") or cached_plan.get("error"):
            return None  # 分解失败，回退到纯对话

        steps = cached_plan["steps"]
        has_deps = any(s.get("depends_on") for s in steps)

        # 有依赖 → WorkflowRunner
        if len(steps) >= 2 and has_deps:
            if on_progress:
                on_progress(f"⚡ 启动工作流引擎\n共 {len(steps)} 个步骤，检测到步骤间存在依赖关系，将按拓扑顺序执行")

            from core.workflow import WorkflowRunner, plan_to_steps, format_workflow_result
            wf_steps = plan_to_steps(cached_plan, user_input=user_message)
            runner = WorkflowRunner(
                goal=user_message, on_progress=on_progress,
                on_confirm=on_confirm, session_id=self.session_id,
            )
            wf_result = await runner.execute(wf_steps)

            response = format_workflow_result(wf_result)
            self.messages.append({"role": "assistant", "content": response})
            self.save_session()

            # 尝试技能沉淀
            if wf_result.success and len(wf_steps) >= 2:
                self._try_precipitate_skill(user_message, cached_plan, on_progress)

            duration_ms = int((time.time() - start_time) * 1000)
            execution_log.log_task(user_input=user_message, success=wf_result.success,
                                   duration_ms=duration_ms, session_id=self.session_id)
            return self._build_result(response, 1)

        # 无依赖 → 注入计划到 system prompt，让 LLM 串行执行
        plan_text = f"📋 目标：{cached_plan.get('goal', user_message)}\n"
        for step in steps:
            deps = step.get("depends_on", [])
            dep_str = f" (依赖步骤 {','.join(map(str, deps))})" if deps else ""
            plan_text += f"  {step['id']}. {step['action']}{dep_str}\n"
        self.messages.append({"role": "system", "content": f"[任务规划]\n{plan_text}\n\n请按以上步骤逐步执行。"})

        # 记录路由决策
        execution_log.log_routing_decision(
            user_message,
            candidates=[{"skill": name, "score": round(s, 3)} for name, s in (routing.candidates or [])],
            fallback_to_decompose=True,
        )

        # 走到路径 D 继续执行
        return await self._path_llm_chat(user_message, on_progress, on_confirm, start_time)

    # ═══ 路径 D：纯 LLM 对话 ═══

    async def _path_llm_chat(self, user_message, on_progress, on_confirm, start_time):
        """路径 D：纯 LLM 对话 + function calling

        v2.1 改进：
        - 同类错误归类：按工具方法类别追踪失败，同类失败 2 次自动提示换方案
        - 中期自反思：每 4 次工具调用检查失败率，≥ 2 次失败触发自反思
        - 统一并行/串行执行路径，减少代码重复
        """
        _success_count = 0
        _search_done = False
        _MAX_FAILS = 3
        rounds = 0

        # 类别级失败追踪
        _failed_categories: dict = {}  # {category: consecutive_fail_count}
        _category_hint_injected: set = set()  # 已注入提示的类别，避免重复

        while self.tool_call_count < config.MAX_TOOL_CALLS_PER_TURN:
            if self.is_cancelled():
                fallback = "操作已被用户取消。"
                self.messages.append({"role": "assistant", "content": fallback})
                return self._build_result(fallback, rounds)

            available_schemas = [
                s for s in registry.get_schemas()
                if registry.get(s["function"]["name"]).is_available()
            ]
            response = await chat(self.messages, tools=available_schemas)
            rounds += 1

            if "_usage" in response:
                self._token_usage.append(response["_usage"])

            # 上下文过长自愈：截断后重试一次
            if response.get("_context_overflow"):
                logger.info("上下文过长，自动截断重试")
                self._trim_context()
                self._sanitize_messages()
                response = await chat(self.messages, tools=available_schemas)
                rounds += 1
                if "_usage" in response:
                    self._token_usage.append(response["_usage"])

            if response.get("_timeout") or response.get("_error"):
                self.messages.append({"role": "assistant", "content": response["content"]})
                return self._build_result(response["content"], rounds)

            # 纯文本回复 → 完成
            if "tool_calls" not in response:
                assistant_msg = response["content"]
                self.messages.append({"role": "assistant", "content": assistant_msg})
                if config.AUTO_MEMO:
                    self._process_memos(assistant_msg)

                # 尝试技能沉淀
                if self.tool_call_count >= 3:
                    self._try_precipitate_skill(user_message, None, on_progress)

                # 记录网站操作经验（供未来触发记忆使用）
                self._record_website_experience(user_message)

                self.save_session()
                duration_ms = int((time.time() - start_time) * 1000)
                execution_log.log_task(user_input=user_message, success=True,
                                       duration_ms=duration_ms, session_id=self.session_id)
                return self._build_result(assistant_msg, rounds)

            # 有工具调用
            self.messages.append(response)
            self.tool_call_count += len(response.get("tool_calls", []))

            # Phase 3: 每 20 次工具调用触发后台自优化（不阻塞本次响应）
            if self.tool_call_count % 20 == 0 and self.tool_call_count > 0:
                asyncio.create_task(self._run_optimization_background())

            # 死循环检测
            self._detect_tool_loop()

            # ── 统一执行工具（并行/串行） ──
            tool_calls = response["tool_calls"]

            async def _run_one(tc):
                """执行单个工具调用"""
                if self.is_cancelled():
                    return tc["id"], json.dumps({"cancelled": True}), tc["function"]["name"]
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                result = await self._execute_tool(func_name, args, on_confirm=on_confirm)
                return tc["id"], result, func_name

            if len(tool_calls) > 1 and not self.is_cancelled():
                results = await asyncio.gather(*[_run_one(tc) for tc in tool_calls],
                                               return_exceptions=True)
            else:
                results = []
                for tc in tool_calls:
                    try:
                        results.append(await _run_one(tc))
                    except Exception as e:
                        results.append(e)

            # ── 处理结果 + 类别级失败追踪 ──
            for item in results:
                if isinstance(item, Exception):
                    continue
                tc_id, result, func_name = item
                self.messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})

                had_result = self._check_tool_had_result(result)
                if had_result:
                    _success_count += 1
                    # 成功 → 重置该类别的连续失败计数
                    cat = get_tool_category(func_name)
                    _failed_categories.pop(cat, None)
                    if func_name in ("web_search", "search"):
                        _search_done = True
                else:
                    # 失败 → 按类别累计
                    cat = get_tool_category(func_name)
                    _failed_categories[cat] = _failed_categories.get(cat, 0) + 1

                    # 同类失败 ≥ 2 次 → 注入策略提示（每个类别只注入一次）
                    if (_failed_categories[cat] >= 2
                            and cat not in _category_hint_injected
                            and cat in CATEGORY_FAILURE_HINTS):
                        self.messages.append({
                            "role": "system",
                            "content": CATEGORY_FAILURE_HINTS[cat],
                        })
                        _category_hint_injected.add(cat)
                        if on_progress:
                            on_progress(f"⚠️ {cat} 类工具连续失败，已提示换方案")

            # 搜索完成 → 提示收手
            if _search_done and _success_count >= 2 and self.tool_call_count >= 3:
                self.messages.append({"role": "system",
                    "content": "[提示] 已获取搜索结果，请直接总结回复用户。"})

            # 总连续失败 → 强制停止
            total_recent_fails = sum(_failed_categories.values())
            if total_recent_fails >= _MAX_FAILS:
                self.messages.append({"role": "system",
                    "content": f"[提示] 连续 {total_recent_fails} 次失败，请停止调用工具。"})

            # ── 中期自反思检查点：每 4 次工具调用检查一次 ──
            if self.tool_call_count > 0 and self.tool_call_count % 4 == 0:
                recent_fails = sum(
                    1 for t in self.tool_log[-4:]
                    if "error" in t.get("result_preview", "").lower()
                    or "blocked" in t.get("result_preview", "").lower()
                )
                if recent_fails >= 2:
                    self.messages.append({"role": "system", "content":
                        f"[自反思] 最近 4 次工具调用中 {recent_fails} 次失败。"
                        f"请重新评估当前方案是否正确。如果连续失败，"
                        f"考虑：1) 换一种完全不同的方法 2) 直接告诉用户当前遇到的困难。"})
                    if on_progress:
                        on_progress(f"🤔 自反思：最近 4 次调用 {recent_fails} 次失败，正在重新评估方案")

            self._trim_context()

        # 工具调用达到上限
        fallback = f"⚠️ 工具调用达到上限({config.MAX_TOOL_CALLS_PER_TURN}次)，自动停止。"
        self.messages.append({"role": "assistant", "content": fallback})
        self.save_session()
        return self._build_result(fallback, rounds)

    # ═══ 辅助方法 ═══

    def _check_tool_had_result(self, result: str) -> bool:
        """判断工具是否产生了有效结果（兼容新旧两种格式）"""
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                # 新格式：ToolResult（success 字段明确）
                if "success" in parsed:
                    return parsed["success"]
                # 旧格式：error/blocked 表示失败
                if parsed.get("error") or parsed.get("_tool_failed") or parsed.get("blocked"):
                    return False
                # 旧格式：有数据字段表示成功
                if parsed.get("data") or parsed.get("results"):
                    return True
                if parsed.get("content") or parsed.get("text") or parsed.get("base64"):
                    return True
        except (json.JSONDecodeError, TypeError):
            if result and len(str(result)) > 20:
                return True
        return False

    def _detect_tool_loop(self):
        """检测工具死循环（同工具同参数连续 3 次）"""
        recent_sigs = []
        for m in self.messages[-10:]:
            if m.get("role") == "assistant" and "tool_calls" in m:
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    sig = f"{fn.get('name', '')}:{fn.get('arguments', '')[:80]}"
                    recent_sigs.append(sig)
        if len(recent_sigs) >= 3 and len(set(recent_sigs[-3:])) == 1:
            self.messages.append({"role": "system",
                "content": f"[循环检测] 你已连续 3 次调用相同工具 {recent_sigs[-1].split(':')[0]}。"
                           f"请换一种方式完成任务。"})

    def _try_precipitate_skill(self, user_message, plan, on_progress):
        """尝试技能沉淀（BM25 语义去重由 staging.stage() 内部处理）"""
        if not config.AUTO_SKILL_PRECIPITATE:
            return
        try:
            from core.intent_router import generate_skill_md
            from skills.staging import SkillStaging

            if plan and plan.get("skill_name"):
                skill_md = generate_skill_md(user_message, plan, [])
                if skill_md:
                    staging = SkillStaging()
                    result = staging.stage(plan["skill_name"], skill_md)
                    if result and on_progress:
                        on_progress(f"💡 新技能已暂存: {plan['skill_name']}")
                    elif result is None and on_progress:
                        on_progress(f"💡 技能 '{plan['skill_name']}' 与已有技能重复，跳过")
        except Exception:
            pass

    def _record_website_experience(self, user_message: str):
        """从成功的浏览器任务中提取网站操作经验，写入触发记忆

        当 agent 用浏览器工具成功完成任务后，自动记录：
        - 访问了哪些域名
        - 用了什么工具序列
        - 用户的原始任务描述

        下次用户提到相同域名时，这些经验会自动注入。
        """
        # 检查本次是否用了浏览器工具
        browser_used = any(
            t.get("tool", "").startswith("ab_")
            for t in self.tool_log[-10:]
        )
        if not browser_used:
            return

        # 提取访问过的 URL
        urls = []
        for t in self.tool_log[-10:]:
            if t.get("tool") in ("ab_open", "ab_navigate_and_snapshot", "ab_snapshot_click"):
                url = t.get("args", {}).get("url", "")
                if url:
                    urls.append(url)

        if not urls:
            return

        # 从 URL 提取域名
        from urllib.parse import urlparse
        domains = set()
        for url in urls:
            try:
                parsed = urlparse(url)
                if parsed.netloc:
                    domains.add(parsed.netloc)
            except Exception:
                pass

        if not domains:
            return

        # 记录经验：域名 + 任务描述 + 使用的工具序列
        tool_sequence = [t.get("tool") for t in self.tool_log[-10:] if t.get("tool")]
        experience = (
            f"[网站经验] 域名: {', '.join(domains)} | "
            f"任务: {user_message[:80]} | "
            f"工具序列: {' → '.join(tool_sequence[-5:])}"
        )

        # 触发标签：域名 + 域名前缀（bilibili.com → bilibili）
        triggers = list(domains)
        for d in domains:
            prefix = d.split(".")[0]
            if prefix and prefix not in triggers:
                triggers.append(prefix)

        self.memory.save_daily(experience, triggers=triggers)

    def _build_result(self, response: str, rounds: int) -> dict:
        total_prompt = sum(u.get("prompt_tokens", 0) for u in self._token_usage)
        total_completion = sum(u.get("completion_tokens", 0) for u in self._token_usage)
        total_tokens = sum(u.get("total_tokens", 0) for u in self._token_usage)
        estimated_cost = (total_prompt * 0.5 + total_completion * 2.0) / 1_000_000

        # 自我诊断：本次会话的工具效果统计
        diagnosis = self._build_diagnosis()

        return {
            "response": response,
            "tool_calls": self.tool_log[-10:],
            "stats": {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_tokens,
                "tool_calls_count": self.tool_call_count,
                "rounds": rounds,
                "estimated_cost_cny": round(estimated_cost, 4),
            },
            "diagnosis": diagnosis,
        }

    def _build_diagnosis(self) -> dict:
        """本次会话的工具效果诊断"""
        if not self.tool_log:
            return {}

        total = len(self.tool_log)
        failed = [t for t in self.tool_log if "error" in t.get("result_preview", "").lower()
                  or "blocked" in t.get("result_preview", "").lower()]
        failed_count = len(failed)
        success_rate = round((total - failed_count) / total, 2) if total > 0 else 1.0

        # 失败工具分布
        fail_tools = {}
        for t in failed:
            name = t.get("tool", "unknown")
            fail_tools[name] = fail_tools.get(name, 0) + 1

        # 平均耗时
        avg_ms = sum(t.get("elapsed_ms", 0) for t in self.tool_log) // total if total > 0 else 0

        result = {
            "tool_calls_total": total,
            "tool_calls_failed": failed_count,
            "success_rate": success_rate,
            "avg_latency_ms": avg_ms,
        }

        if fail_tools:
            result["failed_tools"] = fail_tools
        if failed_count > 0:
            result["hint"] = f"本次 {failed_count}/{total} 次工具调用失败"
            if fail_tools:
                top_fail = max(fail_tools, key=fail_tools.get)
                result["hint"] += f"，主要集中在 {top_fail}"

        return result

    def get_history(self) -> list:
        return [m for m in self.messages if m["role"] != "system"]

    def get_tool_log(self) -> list:
        return self.tool_log

    def get_context_stats(self) -> dict:
        total_chars = sum(len(m.get("content", "")) for m in self.messages)
        return {
            "total_messages": len(self.messages),
            "total_chars": total_chars,
            "estimated_tokens": total_chars // 2,
        }

    # ═══ Phase 3: 后台自我优化 ═══

    async def _run_optimization_background(self):
        """后台执行自我优化周期，不抛异常影响主流程"""
        try:
            from core.self_optimizer import self_optimization_cycle
            from data.execution_log import get_recent_tool_calls
            from core.workflow_templates import get_template_engine

            logs = get_recent_tool_calls(limit=50)
            if not logs:
                return

            engine = get_template_engine()
            await self_optimization_cycle(
                self._effectiveness,
                logs,
                engine.templates,
                registry
            )
        except Exception:
            import logging
            logging.getLogger("conversation").debug("后台优化已跳过", exc_info=True)

    def reset(self):
        if self._browser_session:
            self._browser_session.close()
            self._browser_session = None
        self.messages = []
        self.tool_log = []
        self._token_usage = []
        self._init_system()
        self.save_session()


class ConversationManager:
    """多会话管理"""

    def __init__(self):
        self.sessions: dict[str, Conversation] = {}
        atexit.register(self._cleanup_all)

    def _cleanup_all(self):
        for conv in self.sessions.values():
            if conv._browser_session:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(conv.cleanup())
                    else:
                        loop.run_until_complete(conv.cleanup())
                except Exception:
                    pass

    def get_or_create(self, session_id: str = "default") -> Conversation:
        if session_id not in self.sessions:
            self.sessions[session_id] = Conversation(session_id)
        return self.sessions[session_id]

    def list_sessions(self) -> list:
        return list(self.sessions.keys())

    def delete_session(self, session_id: str):
        conv = self.sessions.pop(session_id, None)
        if conv:
            try:
                os.remove(conv._session_path())
            except OSError:
                pass
