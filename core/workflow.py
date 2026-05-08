# -*- coding: utf-8 -*-
"""
工作流执行器 — 轻量级多步骤任务执行引擎

与 sub_agent.py 的 Orchestrator 的区别：
- Orchestrator: 每步 spawn 独立 SubAgent（有自己的 LLM 对话），重量级
- WorkflowRunner: 直接调用工具，只在"需要推理"时才问 LLM，轻量级

设计原则：
- 单步工具直接执行，不问 LLM
- "auto" 工具或复杂参数才走 LLM 决策
- 步骤间结果自动传递（上一步输出 → 下一步 context）
- 每步独立重试，失败不拖垮整个工作流
- v2.0: ExecutionProfile 合规校验控制执行面
"""
import json
import os
import re
import time
import asyncio
from dataclasses import dataclass, field
from typing import Callable, Optional, List, Dict, Any
from tools.registry import registry
try:
    from data import execution_log
except ImportError:
    execution_log = None  # 测试环境下可选

# ExecutionProfile 已移除（v5：不再由元结构控制执行参数）


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class WorkflowStep:
    """单个工作流步骤"""
    id: int                          # 步骤编号（从 1 开始）
    action: str                      # 步骤描述
    tool: str = "auto"               # 工具名，"auto" 表示由 LLM 决定
    params: Dict[str, Any] = field(default_factory=dict)  # 工具参数
    depends_on: List[int] = field(default_factory=list)    # 依赖的步骤 ID
    verify: str = ""                 # 验证方法描述
    retry: int = 2                   # 最大重试次数
    timeout: float = 30.0            # 单步超时（秒）
    risk: str = "low"                # 风险等级: low / medium / high
    skipped: bool = False            # 被 Profile 合规校验跳过


@dataclass
class StepResult:
    """单步执行结果"""
    step_id: int
    success: bool
    output: str = ""                 # 工具返回的结果
    tool_used: str = ""              # 实际使用的工具名
    elapsed_ms: int = 0
    retries: int = 0                 # 实际重试次数
    error: Optional[str] = None
    skipped: bool = False            # 因依赖失败而跳过


@dataclass
class WorkflowResult:
    """整个工作流的执行结果"""
    success: bool
    goal: str
    step_results: List[StepResult] = field(default_factory=list)
    summary: str = ""
    elapsed_ms: int = 0
    steps_total: int = 0
    steps_success: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0


# ═══════════════════════════════════════════════════════════
# 工作流执行器
# ═══════════════════════════════════════════════════════════

class WorkflowRunner:
    """
    轻量级工作流执行器。

    用法：
        runner = WorkflowRunner(goal="打开微信发消息", on_progress=callback)
        result = await runner.execute(steps)

    执行策略：
    1. 按依赖拓扑排序步骤
    2. 无依赖的步骤可并行
    3. 有依赖的步骤等前置完成后再执行
    4. tool="auto" 时用 LLM 决定用哪个工具
    5. tool 是具体工具名时直接调用
    """

    def __init__(self, goal: str = "", on_progress: Callable = None,
                 on_confirm: Callable = None, session_id: str = "",
                 max_parallel: int = 3):
        self.goal = goal
        self.on_progress = on_progress
        self.on_confirm = on_confirm or (lambda cmd: False)
        self.session_id = session_id
        self.max_parallel = max_parallel
        self._step_results: Dict[int, StepResult] = {}

    async def execute(self, steps: List[WorkflowStep]) -> WorkflowResult:
        """
        执行工作流。

        Args:
            steps: 工作流步骤列表

        Returns:
            WorkflowResult 包含每步结果和整体摘要
        """
        start = time.time()
        self._step_results = {}

        if not steps:
            return WorkflowResult(success=True, goal=self.goal,
                                  summary="空工作流，无需执行")

        # 按依赖拓扑排序，分层执行
        layers = self._topological_layers(steps)
        # v2.0: Profile 合规校验 — 控制面约束执行面
        steps = self._profile_compliance_check(steps)
        # v2.1: 步骤相关性校验 — 不相关的步骤降级为 auto
        steps = self._validate_step_relevance(steps)
        steps_by_id = {s.id: s for s in steps}

        self._report(f"🚀 工作流开始：{self.goal}（{len(steps)} 步，{len(layers)} 层）")

        for layer_idx, layer in enumerate(layers):
            self._report(f"📍 第 {layer_idx + 1} 层：步骤 {layer}")

            # 同一层内的步骤可并行
            tasks = []
            for step_id in layer:
                step = steps_by_id[step_id]
                # 收集依赖结果作为上下文
                dep_results = {
                    d: self._step_results[d]
                    for d in step.depends_on
                    if d in self._step_results
                }
                tasks.append(self._execute_step(step, dep_results))

            # 并行执行（限制并发数）
            if len(tasks) <= self.max_parallel:
                results = await asyncio.gather(*tasks, return_exceptions=True)
            else:
                # 分批执行
                results = []
                for i in range(0, len(tasks), self.max_parallel):
                    batch = tasks[i:i + self.max_parallel]
                    batch_results = await asyncio.gather(*batch, return_exceptions=True)
                    results.extend(batch_results)

            # 记录结果，检查是否需要中止
            abort = False
            for step_id, result in zip(layer, results):
                if isinstance(result, Exception):
                    result = StepResult(
                        step_id=step_id, success=False,
                        error=f"执行异常: {str(result)}",
                    )
                self._step_results[step_id] = result

                # 高风险步骤失败 → 中止整个工作流
                step = steps_by_id[step_id]
                if not result.success and not result.skipped:
                    if step.risk == "high":
                        self._report(f"❌ 高风险步骤 {step_id} 失败，中止工作流")
                        abort = True
                    else:
                        self._report(f"⚠️ 步骤 {step_id} 失败: {result.error}，继续执行")

            if abort:
                # 标记剩余步骤为跳过
                for layer_rest in layers[layer_idx + 1:]:
                    for sid in layer_rest:
                        if sid not in self._step_results:
                            self._step_results[sid] = StepResult(
                                step_id=sid, success=False, skipped=True,
                                error="工作流已中止",
                            )
                break

        # 构建结果
        elapsed_ms = int((time.time() - start) * 1000)
        all_results = [self._step_results.get(s.id, StepResult(step_id=s.id, success=False, skipped=True))
                       for s in steps]

        success_count = sum(1 for r in all_results if r.success)
        fail_count = sum(1 for r in all_results if not r.success and not r.skipped)
        skip_count = sum(1 for r in all_results if r.skipped)
        all_success = fail_count == 0 and skip_count == 0

        summary = self._build_summary(all_results)

        self._report(f"{'✅' if all_success else '❌'} 工作流完成：{success_count}成功 / {fail_count}失败 / {skip_count}跳过（{elapsed_ms}ms）")

        return WorkflowResult(
            success=all_success,
            goal=self.goal,
            step_results=all_results,
            summary=summary,
            elapsed_ms=elapsed_ms,
            steps_total=len(steps),
            steps_success=success_count,
            steps_failed=fail_count,
            steps_skipped=skip_count,
        )

    async def _execute_step(self, step: WorkflowStep,
                             dep_results: Dict[int, StepResult]) -> StepResult:
        """执行单个步骤（含重试逻辑）"""
        start = time.time()
        retries = 0
        last_error = None

        # 构建步骤上下文（注入依赖结果）
        enriched_params = dict(step.params)
        if dep_results:
            dep_context = []
            for dep_id, dep_result in dep_results.items():
                if dep_result.success:
                    dep_context.append(f"[步骤{dep_id}结果] {dep_result.output[:500]}")
                else:
                    dep_context.append(f"[步骤{dep_id}失败] {dep_result.error}")
            enriched_params["_dep_context"] = "\n".join(dep_context)

        # 高风险步骤需要确认
        if step.risk in ("medium", "high"):
            cmd_desc = f"步骤{step.id}: {step.action}"
            if not self.on_confirm(cmd_desc):
                return StepResult(
                    step_id=step.id, success=False,
                    error="用户拒绝执行",
                    elapsed_ms=int((time.time() - start) * 1000),
                )

        for attempt in range(step.retry + 1):
            retries = attempt
            try:
                if step.tool == "auto":
                    # auto 模式：用 LLM 决定工具并执行
                    result = await self._execute_auto_step(step, enriched_params)
                else:
                    # 指定工具：直接调用
                    result = await self._execute_tool_step(step, enriched_params)

                if result.success:
                    result.retries = retries
                    result.elapsed_ms = int((time.time() - start) * 1000)

                    # 验证（如果有）
                    if step.verify and result.success:
                        verified = self._verify_result(result.output, step.verify)
                        if not verified:
                            last_error = f"验证失败: {step.verify}"
                            self._report(f"  🔄 步骤 {step.id} 验证失败，重试 ({attempt + 1}/{step.retry + 1})")
                            continue

                    self._report(f"  ✅ 步骤 {step.id} 完成: {step.action}")
                    return result
                else:
                    last_error = result.error
                    if attempt < step.retry:
                        self._report(f"  🔄 步骤 {step.id} 失败，重试 ({attempt + 1}/{step.retry + 1}): {last_error}")
                        await asyncio.sleep(1 * (attempt + 1))  # 指数退避

            except asyncio.TimeoutError:
                last_error = f"超时（{step.timeout}s）"
                if attempt < step.retry:
                    self._report(f"  🔄 步骤 {step.id} 超时，重试 ({attempt + 1}/{step.retry + 1})")
            except Exception as e:
                last_error = str(e)
                if attempt < step.retry:
                    self._report(f"  🔄 步骤 {step.id} 异常，重试 ({attempt + 1}/{step.retry + 1}): {last_error}")

        # 所有重试用尽
        return StepResult(
            step_id=step.id, success=False,
            error=last_error or "未知错误",
            retries=retries,
            elapsed_ms=int((time.time() - start) * 1000),
        )

    async def _execute_tool_step(self, step: WorkflowStep,
                                  params: Dict[str, Any]) -> StepResult:
        """调用指定工具。如果 params 缺少必要参数，自动用 LLM 推导。"""
        # 清理内部参数（不传给工具）
        clean_params = {k: v for k, v in params.items() if not k.startswith("_")}

        # P0 修复：run_command 必须有 cwd，否则测试结果写错目录
        if step.tool == "run_command" and not clean_params.get("cwd"):
            if self.goal:
                import re
                dir_match = re.search(r'([A-Za-z]:\\[^\s,，。]+)', self.goal)
                if dir_match:
                    clean_params["cwd"] = dir_match.group(1)
            if not clean_params.get("cwd"):
                clean_params["cwd"] = os.getcwd()

        # v4.2: pytest 前置依赖检查 — 自动安装缺失的测试依赖
        if step.tool == "run_command":
            cmd = clean_params.get("command", "")
            if "pytest" in cmd and "pip install" not in cmd:
                check = await self._ensure_pytest_available(clean_params.get("cwd"))
                if not check["ok"]:
                    return StepResult(
                        step_id=step.id, success=False,
                        error=f"pytest 不可用: {check['error']}",
                    )

        # v2.2: 检查工具 schema 的 required 字段，缺少必要参数时用 LLM 补全
        tool_def = registry.get(step.tool)
        if tool_def:
            required = tool_def.schema.get("parameters", {}).get("required", [])
            missing = [r for r in required if r not in clean_params]
            if missing:
                # 用 LLM 从步骤描述中推导缺失参数
                inferred = await self._infer_params_via_llm(step, missing)
                if inferred:
                    clean_params.update(inferred)
                else:
                    return StepResult(
                        step_id=step.id, success=False,
                        error=f"缺少必要参数: {missing}，且 LLM 推导失败",
                    )

        try:
            result_raw = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, registry.execute, step.tool, clean_params
                ),
                timeout=step.timeout,
            )
        except asyncio.TimeoutError:
            return StepResult(step_id=step.id, success=False, error=f"工具超时（{step.timeout}s）")
        except Exception as e:
            return StepResult(step_id=step.id, success=False, error=f"工具异常: {str(e)}")

        # 检查结果
        success = True
        error = None
        try:
            parsed = json.loads(result_raw)
            if isinstance(parsed, dict):
                if parsed.get("error"):
                    success = False
                    error = parsed.get("message", parsed.get("error", ""))
                if parsed.get("blocked"):
                    success = False
                    error = f"安全拦截: {parsed.get('reason', '')}"
                # v4.2: 检查 success 字段（run_command 等工具用此字段表示执行结果）
                if parsed.get("success") is False and success:
                    success = False
                    error = parsed.get("stderr", "") or parsed.get("message", "") or f"命令退出码: {parsed.get('returncode', '?')}"
                # v4.2: 检查门禁拦截
                if parsed.get("blocked_by_test"):
                    success = False
                    error = parsed.get("error", "测试门禁拦截")
        except (json.JSONDecodeError, TypeError):
            pass

        return StepResult(
            step_id=step.id,
            success=success,
            output=str(result_raw)[:2000],
            tool_used=step.tool,
            error=error,
        )

    async def _infer_params_via_llm(self, step: WorkflowStep,
                                     missing_params: list) -> Optional[Dict[str, Any]]:
        """当工具缺少必要参数时，用 LLM 从步骤描述中推导"""
        from core.llm import chat

        tool_def = registry.get(step.tool)
        if not tool_def:
            return None

        # 构建参数 schema 信息
        props = tool_def.schema.get("parameters", {}).get("properties", {})
        param_info = []
        for name in missing_params:
            desc = props.get(name, {}).get("description", name)
            param_info.append(f"- {name}: {desc}")

        dep_ctx = ""
        if step.params:
            dep_ctx = f"\n已知参数: {json.dumps(step.params, ensure_ascii=False)}"

        prompt = f"""根据以下步骤描述，推导工具 "{step.tool}" 的缺失参数。

步骤描述: {step.action}
目标: {self.goal}
缺失参数:
{chr(10).join(param_info)}
{dep_ctx}

请只输出一个 JSON 对象，包含缺失参数的值。例如：{{"url": "https://example.com"}}
不要输出其他内容。"""

        messages = [
            {"role": "system", "content": "你是参数推导器。只输出 JSON，不要多余内容。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await chat(messages, temperature=0.1, use_ollama=True)
            if response.get("_error") or response.get("_timeout"):
                return None
            content = response["content"].strip()
            # 提取 JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            return json.loads(content)
        except Exception:
            return None

    async def _execute_auto_step(self, step: WorkflowStep,
                                  params: Dict[str, Any]) -> StepResult:
        """auto 模式：用 LLM 决定用什么工具"""
        from core.llm import chat

        # 构建工具列表（只给相关的工具 schema）
        schemas = registry.get_schemas()

        # 用依赖结果丰富上下文
        dep_ctx = params.get("_dep_context", "")
        user_msg = f"任务：{step.action}"
        if dep_ctx:
            user_msg += f"\n\n前置步骤结果：\n{dep_ctx}"

        messages = [
            {"role": "system", "content": (
                "你是一个工具执行助手。用户会给你一个具体任务，你需要调用合适的工具完成它。"
                "如果任务简单不需要工具，直接用文字回答。"
                "每步只做一件事，不要多做。"
            )},
            {"role": "user", "content": user_msg},
        ]

        try:
            response = await chat(messages, tools=schemas, temperature=0.1)
        except Exception as e:
            return StepResult(step_id=step.id, success=False, error=f"LLM 调用失败: {str(e)}")

        if response.get("_error") or response.get("_timeout"):
            return StepResult(step_id=step.id, success=False,
                              error=response.get("content", "LLM 错误"))

        # 没有工具调用 → LLM 直接回答
        if "tool_calls" not in response:
            return StepResult(
                step_id=step.id, success=True,
                output=response.get("content", ""),
                tool_used="llm_direct",
            )

        # 有工具调用 → 执行第一个工具（单步只做一个）
        tc = response["tool_calls"][0]
        func_name = tc["function"]["name"]
        try:
            func_args = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            func_args = {}

        # 合并 plan params（plan 里的参数优先）
        for k, v in step.params.items():
            if not k.startswith("_") and k not in func_args:
                func_args[k] = v

        tool_step = WorkflowStep(
            id=step.id, action=step.action,
            tool=func_name, params=func_args,
            timeout=step.timeout,
        )
        return await self._execute_tool_step(tool_step, func_args)

    def _verify_result(self, output: str, verify_desc: str) -> bool:
        """
        简单验证：检查输出是否包含预期内容。
        目前用关键词匹配，未来可以用 LLM 做语义验证。
        """
        if not verify_desc:
            return True

        # 如果输出是 JSON，检查 success 字段
        try:
            parsed = json.loads(output)
            if isinstance(parsed, dict):
                if parsed.get("error") or parsed.get("blocked"):
                    return False
                if parsed.get("success"):
                    return True
        except (json.JSONDecodeError, TypeError):
            pass

        # 关键词匹配验证
        verify_lower = verify_desc.lower()
        output_lower = output.lower()

        # "没有报错" 类验证
        if "没有报错" in verify_desc or "无错误" in verify_desc:
            error_keywords = ["error", "exception", "traceback", "failed", "失败"]
            return not any(kw in output_lower for kw in error_keywords)

        # "包含xxx" 类验证
        if "包含" in verify_desc:
            keyword = verify_desc.split("包含")[-1].strip()
            return keyword in output

        # 默认通过（无法自动验证时）
        return True

    def _topological_layers(self, steps: List[WorkflowStep]) -> List[List[int]]:
        """
        拓扑排序，返回分层结果。

        每层内的步骤无互相依赖，可以并行执行。
        """
        steps_by_id = {s.id: s for s in steps}
        in_degree = {s.id: len(s.depends_on) for s in steps}
        layers = []
        remaining = set(s.id for s in steps)

        while remaining:
            # 找入度为 0 的节点
            layer = [sid for sid in remaining if in_degree.get(sid, 0) == 0]
            if not layer:
                # 有循环依赖，强制取剩余的
                layer = [min(remaining)]
                self._report(f"⚠️ 检测到循环依赖，强制执行步骤 {layer}")

            layers.append(sorted(layer))

            # 更新入度
            for sid in layer:
                remaining.discard(sid)
                for s in steps:
                    if sid in s.depends_on:
                        in_degree[s.id] -= 1

        return layers

    def _build_summary(self, results: List[StepResult]) -> str:
        """构建执行摘要"""
        lines = [f"📋 目标：{self.goal}"]
        for r in results:
            if r.skipped:
                lines.append(f"  ⏭️ 步骤{r.step_id}: 跳过（{r.error}）")
            elif r.success:
                preview = r.output[:100].replace("\n", " ")
                lines.append(f"  ✅ 步骤{r.step_id}: {r.tool_used} → {preview}")
            else:
                lines.append(f"  ❌ 步骤{r.step_id}: {r.error}")
        return "\n".join(lines)

    def _report(self, msg: str):
        """进度回调"""
        if self.on_progress:
            self.on_progress(msg)

    async def _ensure_pytest_available(self, cwd: str = None) -> dict:
        """检查 pytest 是否可用，不可用则尝试自动安装依赖。
        P1 修复：Windows 兼容（用 python -m pytest 检测，不依赖 shutil.which）。"""
        import shutil
        import sys

        async def _pytest_works() -> bool:
            """用 python -m pytest --version 检测是否可用"""
            try:
                proc = await asyncio.create_subprocess_shell(
                    f"{sys.executable} -m pytest --version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
                await asyncio.wait_for(proc.communicate(), timeout=15)
                return proc.returncode == 0
            except Exception:
                return False

        # 先检测 pytest 是否已可用
        if shutil.which("pytest") or await _pytest_works():
            return {"ok": True}

        # 尝试从 requirements.txt 安装
        req_file = None
        if cwd:
            candidate = os.path.join(cwd, "requirements.txt")
            if os.path.isfile(candidate):
                req_file = candidate
        if not req_file:
            if os.path.isfile("requirements.txt"):
                req_file = "requirements.txt"

        if req_file:
            self._report(f"  📦 pytest 未安装，正在从 {req_file} 安装依赖...")
            install_cmd = f"{sys.executable} -m pip install -r {req_file}"
        else:
            self._report("  📦 pytest 未安装，正在安装...")
            install_cmd = f"{sys.executable} -m pip install pytest"

        try:
            proc = await asyncio.create_subprocess_shell(
                install_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode == 0 and (shutil.which("pytest") or await _pytest_works()):
                self._report("  ✅ 依赖安装完成")
                return {"ok": True}
            else:
                return {"ok": False, "error": f"pip install 失败: {stderr.decode(errors='replace')[:300]}"}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "依赖安装超时（120s）"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _validate_step_relevance(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        """检查每个步骤的工具是否和任务目标相关，中文用 jieba 分词"""
        try:
            import jieba
            def tokenize(text):
                return set(w for w in jieba.lcut(text.lower()) if len(w) > 1)
        except ImportError:
            def tokenize(text):
                return set(text.lower().split())

        goal_words = tokenize(self.goal)
        goal_lower = self.goal.lower()

        # P0: CLI 任务检测 — 如果目标是纯命令行操作，自动跳过浏览器步骤
        cli_keywords = {
            'git', 'clone', 'pull', 'push', 'commit', 'pip', 'npm',
            'apt', 'yum', 'brew', 'wget', 'curl', 'mkdir', 'install',
        }
        is_cli_task = any(kw in goal_lower for kw in cli_keywords)

        for step in steps:
            if step.tool == "auto":
                continue

            # CLI 任务中跳过浏览器步骤
            if is_cli_task and (step.tool.startswith('ab_') or 'browser' in step.tool):
                step.skipped = True
                continue

            # 原有逻辑：jieba 分词重叠检查
            action_words = tokenize(step.action)
            overlap = goal_words & action_words
            if not overlap:
                step.tool = "auto"

        return steps

    def _profile_compliance_check(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        """v3.0: 仅保留安全相关的高风险拦截，去掉策略越权。

        - 不再强制串行（LLM 自主决定是否并行）
        - 不再覆盖步骤的 retry 和 timeout（步骤自己决定）
        - 保留：高风险步骤需要人工确认（安全机制）
        """
        filtered = []
        for step in steps:
            # 保留：高风险步骤需要人工确认（安全机制，不是策略）
            if step.risk == "high":
                if not self.on_confirm(f"⚠️ 高风险步骤: {step.action}"):
                    step.skipped = True
                    continue

            filtered.append(step)

        return filtered


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _fuzzy_tool_match(name: str, available: set) -> str:
    """模糊匹配工具名：search_web → web_search"""
    name_lower = name.lower()
    # 1. 包含关系（带长度约束防误匹配）
    for tool in available:
        if name_lower in tool or tool in name_lower:
            if abs(len(name_lower) - len(tool)) < max(len(name_lower), len(tool)) * 0.5:
                return tool
    # 2. 词序反转
    parts = set(name_lower.replace("-", "_").split("_"))
    for tool in available:
        tool_parts = set(tool.replace("-", "_").split("_"))
        if parts == tool_parts:
            return tool
    return ""


def plan_to_steps(plan: dict, user_input: str = "") -> List[WorkflowStep]:
    """
    将 planner.py 生成的计划转换为 WorkflowStep 列表。

    v2.1: 工具名校验 — 模糊匹配 + 降级为 auto
    v4.3: P0 修复 — run_command 步骤自动注入 cwd，确保测试结果写入正确目录
    v4.4: P2 修复 — write_file/edit_file 从 action 描述提取路径
    v4.4: P3 修复 — 优先从 user_input 提取 cwd（用户原始输入含路径）
    """
    from tools.registry import registry as _registry
    available_tools = set(_registry.get_available_names())

    # P3 修复：优先从 user_input 提取路径（用户原始输入比 LLM 摘要更可靠）
    plan_cwd = ""
    if user_input:
        dir_match = re.search(r'([A-Za-z]:\\[^\s,，。]+)', user_input)
        if dir_match:
            plan_cwd = dir_match.group(1)
    if not plan_cwd:
        plan_cwd = plan.get("cwd", "")
    if not plan_cwd:
        goal = plan.get("goal", "")
        dir_match = re.search(r'([A-Za-z]:\\[^\s,，。]+)', goal)
        if dir_match:
            plan_cwd = dir_match.group(1)

    steps = []
    for s in plan.get("steps", []):
        tool = s.get("tool", "auto")
        # 兜底：LLM 偶尔填 "无"/"none" 等非法值，统一回退到 "auto"
        if not tool or tool.lower() in ("无", "none", "不需要", "null", "n/a", "-"):
            tool = "auto"
        # v2.1: 工具名校验 — 不存在则模糊匹配，匹配不到降级为 auto
        if tool and tool != "auto" and tool not in available_tools:
            fuzzy = _fuzzy_tool_match(tool, available_tools)
            if fuzzy:
                import logging
                logging.getLogger("workflow").info(
                    f"工具名 '{tool}' 模糊匹配为 '{fuzzy}'"
                )
                tool = fuzzy
            else:
                import logging
                logging.getLogger("workflow").warning(
                    f"工具名 '{tool}' 无法匹配任何已知工具，降级为 auto"
                )
                tool = "auto"

        step_params = s.get("params", {})

        # P0 修复：run_command 步骤如果没有 cwd，注入 plan_cwd
        if tool == "run_command" and not step_params.get("cwd") and plan_cwd:
            step_params["cwd"] = plan_cwd

        # P2 修复：write_file/edit_file 步骤如果没有 path，从 action 描述提取
        if tool in ("write_file", "edit_file") and not step_params.get("path"):
            action_text = s.get("action", "")
            # 匹配文件路径：支持正反斜杠，含扩展名
            file_match = re.search(r'[\w/\\\-\.]+\.\w{1,6}', action_text)
            if file_match:
                file_path = file_match.group(0)
                # 如果有 cwd 且路径不是绝对路径，拼接完整路径
                if plan_cwd and not os.path.isabs(file_path):
                    file_path = os.path.join(plan_cwd, file_path)
                step_params["path"] = file_path

        steps.append(WorkflowStep(
            id=s.get("id", len(steps) + 1),
            action=s.get("action", ""),
            tool=tool,
            params=step_params,
            depends_on=s.get("depends_on", []),
            verify=s.get("verify", ""),
            retry=s.get("retry", 2),
            timeout=s.get("timeout", 30.0),
            risk=s.get("risk", "low"),
        ))
    return steps


def format_workflow_result(result: WorkflowResult) -> str:
    """格式化工作流结果为用户可读文本"""
    if result.success:
        return f"✅ {result.goal} — 全部 {result.steps_total} 步完成（{result.elapsed_ms}ms）\n{result.summary}"
    else:
        parts = [f"❌ {result.goal} — {result.steps_success}成功 / {result.steps_failed}失败 / {result.steps_skipped}跳过"]
        parts.append(result.summary)
        return "\n".join(parts)
