# -*- coding: utf-8 -*-
"""WorkflowRunner 单元测试（独立运行，不依赖完整项目）"""
import asyncio
import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Mock 外部依赖（只在本测试文件内生效，不污染全局）
_original_modules = {}
_mocked_modules = ['config', 'data', 'data.execution_log', 'tools.registry',
                   'security.context_sanitizer', 'memory.memory_system', 'core.llm']
for mod in _mocked_modules:
    if mod not in sys.modules:
        _original_modules[mod] = None  # 不存在，标记为需要清理
        sys.modules[mod] = MagicMock()
    else:
        _original_modules[mod] = sys.modules[mod]  # 保存原始引用

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.workflow import (
    WorkflowRunner, WorkflowStep, StepResult, WorkflowResult,
    plan_to_steps, format_workflow_result,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestWorkflowRunner(unittest.TestCase):

    def setUp(self):
        # 每个测试重置 mock，防止测试间干扰
        mock_registry = sys.modules['tools.registry']
        mock_registry.registry.execute.reset_mock()
        mock_registry.registry.execute.return_value = json.dumps({"result": "ok"})

    def test_empty_workflow(self):
        runner = WorkflowRunner(goal="空任务")
        result = run(runner.execute([]))
        self.assertTrue(result.success)
        self.assertEqual(result.steps_total, 0)

    def test_topological_sort(self):
        steps = [
            WorkflowStep(id=1, action="A", depends_on=[]),
            WorkflowStep(id=2, action="B", depends_on=[1]),
            WorkflowStep(id=3, action="C", depends_on=[1]),
            WorkflowStep(id=4, action="D", depends_on=[2, 3]),
        ]
        runner = WorkflowRunner()
        layers = runner._topological_layers(steps)
        self.assertEqual(layers[0], [1])
        self.assertEqual(set(layers[1]), {2, 3})
        self.assertEqual(layers[2], [4])

    def test_topological_sort_linear(self):
        steps = [
            WorkflowStep(id=1, action="A"),
            WorkflowStep(id=2, action="B", depends_on=[1]),
            WorkflowStep(id=3, action="C", depends_on=[2]),
        ]
        runner = WorkflowRunner()
        layers = runner._topological_layers(steps)
        self.assertEqual(layers, [[1], [2], [3]])

    def test_topological_sort_parallel(self):
        steps = [
            WorkflowStep(id=1, action="A"),
            WorkflowStep(id=2, action="B"),
            WorkflowStep(id=3, action="C"),
        ]
        runner = WorkflowRunner()
        layers = runner._topological_layers(steps)
        self.assertEqual(len(layers), 1)
        self.assertEqual(set(layers[0]), {1, 2, 3})

    def test_plan_to_steps(self):
        plan = {
            "goal": "测试",
            "steps": [
                {"id": 1, "action": "步骤1", "tool": "execute_command", "params": {"command": "ls"}},
                {"id": 2, "action": "步骤2", "tool": "auto", "depends_on": [1], "verify": "没有报错"},
            ]
        }
        steps = plan_to_steps(plan)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].tool, "execute_command")
        self.assertEqual(steps[1].depends_on, [1])
        self.assertEqual(steps[1].verify, "没有报错")

    def test_format_result_success(self):
        result = WorkflowResult(
            success=True, goal="测试",
            steps_total=2, steps_success=2, steps_failed=0, steps_skipped=0,
            elapsed_ms=100,
            step_results=[
                StepResult(step_id=1, success=True, output="ok", tool_used="cmd"),
                StepResult(step_id=2, success=True, output="done", tool_used="cmd"),
            ],
            summary="全部完成",
        )
        text = format_workflow_result(result)
        self.assertIn("✅", text)
        self.assertIn("测试", text)

    def test_format_result_failure(self):
        result = WorkflowResult(
            success=False, goal="测试",
            steps_total=2, steps_success=1, steps_failed=1, steps_skipped=0,
            elapsed_ms=100,
            step_results=[
                StepResult(step_id=1, success=True, output="ok", tool_used="cmd"),
                StepResult(step_id=2, success=False, error="失败"),
            ],
        )
        text = format_workflow_result(result)
        self.assertIn("❌", text)

    def test_user_reject(self):
        """用户拒绝高风险操作"""
        steps = [WorkflowStep(id=1, action="删除文件", tool="execute_command",
                              params={"command": "rm -rf /tmp/test"}, risk="high")]
        runner = WorkflowRunner(goal="拒绝测试", on_confirm=lambda cmd: False)
        result = run(runner.execute(steps))
        self.assertFalse(result.step_results[0].success)
        self.assertIn("拒绝", result.step_results[0].error)

    def test_user_accept(self):
        """用户同意高风险操作"""
        # Mock registry.execute 返回成功
        mock_registry = sys.modules['tools.registry']
        mock_registry.registry.execute.return_value = json.dumps({"success": True, "output": "done"})

        steps = [WorkflowStep(id=1, action="删除文件", tool="execute_command",
                              params={"command": "rm /tmp/test"}, risk="high")]
        runner = WorkflowRunner(goal="接受测试", on_confirm=lambda cmd: True)
        result = run(runner.execute(steps))
        self.assertTrue(result.step_results[0].success)

    def test_tool_step_with_mock(self):
        """工具步骤执行（mock）"""
        mock_registry = sys.modules['tools.registry']
        mock_registry.registry.execute.return_value = json.dumps({"result": "hello"})

        steps = [WorkflowStep(id=1, action="echo", tool="execute_command",
                              params={"command": "echo hello"})]
        runner = WorkflowRunner(goal="mock测试")
        result = run(runner.execute(steps))
        self.assertTrue(result.step_results[0].success)
        self.assertEqual(result.step_results[0].tool_used, "execute_command")

    def test_tool_step_blocked(self):
        """工具被安全拦截"""
        mock_registry = sys.modules['tools.registry']
        blocked = json.dumps({"blocked": True, "reason": "危险命令", "risk_level": "high"})
        mock_registry.registry.execute.return_value = blocked
        mock_registry.registry.execute.side_effect = None

        steps = [WorkflowStep(id=1, action="危险操作", tool="execute_command",
                              params={"command": "rm -rf /"})]
        runner = WorkflowRunner(goal="拦截测试")
        result = run(runner.execute(steps))
        self.assertFalse(result.step_results[0].success)
        self.assertIn("拦截", result.step_results[0].error)

    def test_progress_callback(self):
        """进度回调被调用"""
        mock_registry = sys.modules['tools.registry']
        mock_registry.registry.execute.return_value = json.dumps({"ok": True})

        progress = []
        steps = [WorkflowStep(id=1, action="测试", tool="execute_command",
                              params={"command": "echo ok"})]
        runner = WorkflowRunner(goal="回调测试", on_progress=progress.append)
        result = run(runner.execute(steps))
        self.assertTrue(len(progress) > 0)
        self.assertTrue(any("🚀" in p for p in progress))
        self.assertTrue(any("✅" in p for p in progress))

    def test_dependency_chain_mock(self):
        """依赖链：步骤2依赖步骤1"""
        mock_registry = sys.modules['tools.registry']
        mock_registry.registry.execute.return_value = json.dumps({"result": "ok"})

        steps = [
            WorkflowStep(id=1, action="步骤1", tool="cmd1", params={"p": "a"}),
            WorkflowStep(id=2, action="步骤2", tool="cmd2", params={"p": "b"}, depends_on=[1]),
        ]
        runner = WorkflowRunner(goal="依赖测试")
        result = run(runner.execute(steps))
        self.assertEqual(result.steps_total, 2)
        self.assertTrue(all(r.success for r in result.step_results))

    def test_high_risk_abort_on_failure(self):
        """高风险步骤失败 → 中止整个工作流"""
        mock_registry = sys.modules['tools.registry']
        mock_registry.registry.execute.return_value = json.dumps({"error": "失败"})
        mock_registry.registry.execute.side_effect = None

        steps = [
            WorkflowStep(id=1, action="高风险", tool="cmd", params={}, risk="high"),
            WorkflowStep(id=2, action="后续", tool="cmd", params={}, depends_on=[1]),
        ]
        runner = WorkflowRunner(goal="中止测试", on_confirm=lambda c: True)
        result = run(runner.execute(steps))
        self.assertFalse(result.success)
        # 步骤2应该被跳过
        self.assertTrue(result.step_results[1].skipped)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# 清理：恢复被 mock 的模块，避免污染其他测试
import atexit
def _cleanup_mocked_modules():
    for mod in _mocked_modules:
        if mod in _original_modules and _original_modules[mod] is None:
            sys.modules.pop(mod, None)
        elif mod in _original_modules:
            sys.modules[mod] = _original_modules[mod]
atexit.register(_cleanup_mocked_modules)
