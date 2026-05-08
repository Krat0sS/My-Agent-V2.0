# -*- coding: utf-8 -*-
"""WorkflowTemplate 单元测试"""
import asyncio
import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Mock 外部依赖（不覆盖已有的 mock，避免引用断裂）
for mod in ['config', 'data', 'data.execution_log', 'tools.registry',
            'security.context_sanitizer', 'memory.memory_system', 'core.llm']:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.workflow_templates import (
    TemplateEngine, WorkflowTemplate, BUILTIN_TEMPLATES,
    try_template, get_template_engine,
)
from core.workflow import WorkflowStep


class TestTemplateEngine(unittest.TestCase):

    def setUp(self):
        self.engine = TemplateEngine(learned_path="/tmp/test_learned_templates.json")

    def test_builtin_templates_loaded(self):
        self.assertTrue(len(self.engine.templates) >= 6)

    def test_match_send_message(self):
        result = self.engine.match("给张三发一条消息说明天开会")
        self.assertIsNotNone(result)
        tmpl, variables = result
        self.assertEqual(tmpl.name, "send_message")
        self.assertIn("contact", variables)
        self.assertEqual(variables["contact"], "张三")
        self.assertIn("message", variables)

    def test_match_tell_someone(self):
        result = self.engine.match("告诉张三明天开会")
        self.assertIsNotNone(result)
        tmpl, variables = result
        self.assertEqual(tmpl.name, "tell_someone")
        self.assertEqual(variables["contact"], "张三")
        self.assertIn("明天开会", variables["message"])

    def test_match_send_with_app(self):
        result = self.engine.match("打开微信给李四说你好")
        self.assertIsNotNone(result)
        tmpl, variables = result
        self.assertEqual(tmpl.name, "send_message_with_app")
        self.assertEqual(variables["app"], "微信")
        self.assertEqual(variables["contact"], "李四")

    def test_match_organize_files(self):
        result = self.engine.match("整理桌面文件夹里的图片文件")
        self.assertIsNotNone(result)
        tmpl, variables = result
        self.assertEqual(tmpl.name, "organize_files")

    def test_match_backup(self):
        result = self.engine.match("备份Documents到/tmp/backup")
        self.assertIsNotNone(result)
        tmpl, variables = result
        self.assertEqual(tmpl.name, "backup_files")

    def test_match_no_hit(self):
        result = self.engine.match("今天天气怎么样")
        self.assertIsNone(result)

    def test_match_empty_input(self):
        result = self.engine.match("")
        self.assertIsNone(result)

    def test_generate_steps(self):
        match = self.engine.match("给张三发消息说你好")
        self.assertIsNotNone(match)
        tmpl, variables = match
        steps = self.engine.generate_steps(match)
        self.assertTrue(len(steps) > 0)
        self.assertIsInstance(steps[0], WorkflowStep)
        # 检查变量替换
        all_text = str([s.params for s in steps]) + str([s.action for s in steps])
        self.assertIn("张三", all_text, "变量 '张三' 应该被替换到步骤中")

    def test_generate_steps_ids_sequential(self):
        match = self.engine.match("给张三发消息说你好")
        steps = self.engine.generate_steps(match)
        for i, s in enumerate(steps):
            self.assertEqual(s.id, i + 1)

    def test_record_result(self):
        # 用自定义模板避免全局状态干扰
        self.engine.templates.append(WorkflowTemplate(
            name="_test_record", pattern="test", description="test", steps=[]))
        self.engine.record_result("_test_record", True)
        tmpl = next(t for t in self.engine.templates if t.name == "_test_record")
        self.assertEqual(tmpl.use_count, 1)
        self.assertEqual(tmpl.success_count, 1)

    def test_record_failure(self):
        self.engine.templates.append(WorkflowTemplate(
            name="_test_record_fail", pattern="test", description="test", steps=[]))
        self.engine.record_result("_test_record_fail", False)
        tmpl = next(t for t in self.engine.templates if t.name == "_test_record_fail")
        self.assertEqual(tmpl.use_count, 1)
        self.assertEqual(tmpl.success_count, 0)

    def test_success_rate(self):
        tmpl = WorkflowTemplate(name="test", pattern="test", description="test",
                                steps=[], use_count=10, success_count=7)
        self.assertAlmostEqual(tmpl.success_rate, 0.7)

    def test_success_rate_zero(self):
        tmpl = WorkflowTemplate(name="test", pattern="test", description="test",
                                steps=[], use_count=0, success_count=0)
        self.assertAlmostEqual(tmpl.success_rate, 0.0)

    def test_learn_template(self):
        steps = [
            WorkflowStep(id=1, action="打开浏览器", tool="browser_open"),
            WorkflowStep(id=2, action="搜索", tool="web_search", params={"query": "test"}),
        ]
        tmpl = self.engine.learn_template("打开浏览器搜索test", steps, goal="搜索")
        self.assertEqual(tmpl.source, "learned")
        self.assertEqual(tmpl.use_count, 1)
        # 学习后应该能匹配
        result = self.engine.match("打开浏览器搜索test")
        self.assertIsNotNone(result)

    def test_get_stats(self):
        stats = self.engine.get_stats()
        self.assertIn("total", stats)
        self.assertIn("builtin", stats)
        self.assertGreater(stats["builtin"], 0)

    def test_try_template_entry(self):
        result = try_template("给张三发消息说你好")
        self.assertIsNotNone(result)
        tmpl, steps = result
        self.assertTrue(len(steps) > 0)

    def test_try_template_no_hit(self):
        result = try_template("随便说点什么不相关的")
        self.assertIsNone(result)


class TestTemplateMatchingPatterns(unittest.TestCase):
    """测试各种中文表达的模板匹配"""

    def setUp(self):
        self.engine = TemplateEngine(learned_path="/tmp/test_learned_templates2.json")

    def test_various_send_patterns(self):
        patterns = [
            ("给张三发一条消息说明天开会", "send_message"),
            ("发给张三说明天开会", "send_message"),
            ("告诉张三明天开会", "tell_someone"),
            ("跟张三说明天开会", "send_message"),
            ("对张三说明天开会", "send_message"),
        ]
        for p, expected_name in patterns:
            result = self.engine.match(p)
            self.assertIsNotNone(result, f"应该匹配: {p}")
            tmpl, variables = result
            self.assertEqual(tmpl.name, expected_name, f"模板名不匹配: {p}")

    def test_various_app_patterns(self):
        patterns = [
            "打开微信给张三说你好",
            "启动微信给张三说你好",
            "切换到微信给张三说你好",
        ]
        for p in patterns:
            result = self.engine.match(p)
            self.assertIsNotNone(result, f"应该匹配: {p}")
            tmpl, variables = result
            self.assertEqual(tmpl.name, "send_message_with_app", f"应匹配 send_message_with_app: {p}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
