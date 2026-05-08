# -*- coding: utf-8 -*-
"""
集成测试 — 覆盖阶段一~三的核心改动（unittest 版，零外部依赖）

测试范围：
- ToolResult 统一格式
- 工具类别分类
- 记忆触发标签
- 文件操作 ToolResult 格式
- 对话工具结果判断
"""
import json
import os
import sys
import tempfile
import unittest

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 依赖检测
_HAS_HTTPX = False
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    pass

_HAS_DOTENV = False
try:
    import dotenv
    _HAS_DOTENV = True
except ImportError:
    pass


class TestToolResult(unittest.TestCase):
    """验证 ToolResult 的 ok/fail 输出格式"""

    def test_ok_basic(self):
        from tools.tool_utils import ToolResult
        r = json.loads(ToolResult.ok({"content": "hello"}))
        self.assertTrue(r["success"])
        self.assertEqual(r["data"]["content"], "hello")
        self.assertNotIn("error", r)

    def test_ok_empty(self):
        from tools.tool_utils import ToolResult
        r = json.loads(ToolResult.ok())
        self.assertTrue(r["success"])
        self.assertEqual(r["data"], {})

    def test_fail_basic(self):
        from tools.tool_utils import ToolResult
        r = json.loads(ToolResult.fail("文件不存在", "E_NOT_FOUND", recoverable=True))
        self.assertFalse(r["success"])
        self.assertEqual(r["error"], "文件不存在")
        self.assertEqual(r["error_code"], "E_NOT_FOUND")
        self.assertTrue(r["recoverable"])

    def test_fail_with_hint(self):
        from tools.tool_utils import ToolResult
        r = json.loads(ToolResult.fail("权限不足", "E_PERMISSION", hint="检查文件权限"))
        self.assertEqual(r["hint"], "检查文件权限")

    def test_fail_non_recoverable(self):
        from tools.tool_utils import ToolResult
        r = json.loads(ToolResult.fail("致命错误", "E_FATAL", recoverable=False))
        self.assertFalse(r["recoverable"])


class TestToolCategories(unittest.TestCase):
    """验证工具类别反向索引和策略提示"""

    def test_dom_interact(self):
        from tools.tool_utils import get_tool_category
        self.assertEqual(get_tool_category("ab_click"), "dom_interact")
        self.assertEqual(get_tool_category("ab_fill"), "dom_interact")
        self.assertEqual(get_tool_category("ab_type"), "dom_interact")
        self.assertEqual(get_tool_category("ab_find"), "dom_interact")
        self.assertEqual(get_tool_category("ab_hover"), "dom_interact")

    def test_dom_observe(self):
        from tools.tool_utils import get_tool_category
        self.assertEqual(get_tool_category("ab_snapshot"), "dom_observe")
        self.assertEqual(get_tool_category("ab_screenshot"), "dom_observe")
        self.assertEqual(get_tool_category("ab_get_text"), "dom_observe")

    def test_url_navigate(self):
        from tools.tool_utils import get_tool_category
        self.assertEqual(get_tool_category("ab_open"), "url_navigate")
        self.assertEqual(get_tool_category("web_search"), "url_navigate")
        self.assertEqual(get_tool_category("news_search"), "url_navigate")

    def test_file_ops(self):
        from tools.tool_utils import get_tool_category
        self.assertEqual(get_tool_category("read_file"), "file_ops")
        self.assertEqual(get_tool_category("write_file"), "file_ops")
        self.assertEqual(get_tool_category("edit_file"), "file_ops")
        self.assertEqual(get_tool_category("find_files"), "file_ops")

    def test_git(self):
        from tools.tool_utils import get_tool_category
        self.assertEqual(get_tool_category("git_status"), "git")
        self.assertEqual(get_tool_category("git_commit"), "git")
        self.assertEqual(get_tool_category("git_push"), "git")

    def test_memory(self):
        from tools.tool_utils import get_tool_category
        self.assertEqual(get_tool_category("remember"), "memory")
        self.assertEqual(get_tool_category("recall"), "memory")

    def test_unknown(self):
        from tools.tool_utils import get_tool_category
        self.assertEqual(get_tool_category("nonexistent_tool"), "unknown")
        self.assertEqual(get_tool_category(""), "unknown")

    def test_category_hints_cover_core_categories(self):
        from tools.tool_utils import CATEGORY_FAILURE_HINTS
        self.assertIn("dom_interact", CATEGORY_FAILURE_HINTS)
        self.assertIn("dom_observe", CATEGORY_FAILURE_HINTS)
        self.assertIn("url_navigate", CATEGORY_FAILURE_HINTS)
        self.assertIn("file_ops", CATEGORY_FAILURE_HINTS)
        self.assertIn("command", CATEGORY_FAILURE_HINTS)

    def test_all_registered_tools_categorized(self):
        from tools.tool_utils import TOOL_CATEGORIES
        all_categorized = set()
        for tools in TOOL_CATEGORIES.values():
            all_categorized.update(tools)
        self.assertGreaterEqual(len(all_categorized), 60)


class TestFileOpsToolResult(unittest.TestCase):
    """验证 file_ops 插件返回 ToolResult 格式"""

    def test_read_file_nonexistent(self):
        from tools.plugins.file_ops import _read_file
        r = json.loads(_read_file("/nonexistent/path/abc123"))
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "E_NOT_FOUND")
        self.assertTrue(r["recoverable"])
        self.assertIn("hint", r)

    def test_read_file_success(self):
        from tools.plugins.file_ops import _read_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("测试内容 hello")
            path = f.name
        try:
            r = json.loads(_read_file(path))
            self.assertTrue(r["success"])
            self.assertIn("测试内容", r["data"]["content"])
            self.assertEqual(r["data"]["path"], path)
        finally:
            os.unlink(path)

    def test_write_file_success(self):
        from tools.plugins.file_ops import _write_file
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.txt")
            r = json.loads(_write_file(path, "hello world"))
            self.assertTrue(r["success"])
            self.assertEqual(r["data"]["path"], path)
            with open(path) as f:
                self.assertEqual(f.read(), "hello world")

    def test_edit_file_not_found(self):
        from tools.plugins.file_ops import _edit_file
        r = json.loads(_edit_file("/nonexistent/path", "old", "new"))
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "E_NOT_FOUND")

    def test_edit_file_text_not_found(self):
        from tools.plugins.file_ops import _edit_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("hello world")
            path = f.name
        try:
            r = json.loads(_edit_file(path, "NOT_EXIST", "new"))
            self.assertFalse(r["success"])
            self.assertEqual(r["error_code"], "E_NOT_FOUND")
            self.assertTrue(r["recoverable"])
        finally:
            os.unlink(path)


class TestVariableToolsResult(unittest.TestCase):
    """验证 variable_tools 插件返回 ToolResult 格式"""

    def test_set_and_get(self):
        from tools.plugins.variable_tools import _set_variable, _get_variable
        r = json.loads(_set_variable("test_key", "test_value"))
        self.assertTrue(r["success"])
        self.assertEqual(r["data"]["name"], "test_key")

        r = json.loads(_get_variable("test_key"))
        self.assertTrue(r["success"])
        self.assertEqual(r["data"]["value"], "test_value")

    def test_get_nonexistent(self):
        from tools.plugins.variable_tools import _get_variable
        r = json.loads(_get_variable("nonexistent_var_12345"))
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "E_NOT_FOUND")

    def test_list_variables(self):
        from tools.plugins.variable_tools import _set_variable, _list_variables
        _set_variable("list_test_a", "1")
        _set_variable("list_test_b", "2")
        r = json.loads(_list_variables())
        self.assertTrue(r["success"])
        self.assertGreaterEqual(r["data"]["count"], 2)


class TestNormalizePath(unittest.TestCase):
    """验证路径规范化"""

    def test_expanduser(self):
        from tools.tool_utils import normalize_path
        result = normalize_path("~/test")
        self.assertNotIn("~", result)
        self.assertTrue(result.endswith("/test"))

    def test_nfc_normalize(self):
        from tools.tool_utils import normalize_path
        result = normalize_path("/tmp/测试")
        self.assertIn("测试", result)


@unittest.skipUnless(_HAS_DOTENV, "需要 python-dotenv 依赖")
class TestTriggerMemory(unittest.TestCase):
    """验证记忆触发标签系统"""

    def test_save_with_triggers(self):
        from memory.memory_system import MemorySystem
        from config import MEMORY_DIR
        ms = MemorySystem()
        ms.save_daily("[测试] 触发标签测试条目", triggers=["test_trigger", "测试触发"])

        index_file = os.path.join(MEMORY_DIR, "_trigger_index.json")
        self.assertTrue(os.path.exists(index_file))

        with open(index_file) as f:
            index = json.load(f)
        found = any("测试" in str(v.get("triggers", [])) for v in index.values())
        self.assertTrue(found)

    def test_get_triggered_memories(self):
        from memory.memory_system import MemorySystem
        ms = MemorySystem()
        ms.save_daily("[测试] bilibili 视频搜索经验", triggers=["bilibili", "B站", "视频"])

        results = ms.get_triggered_memories("帮我搜一下 bilibili 上的视频")
        self.assertGreater(len(results), 0)
        self.assertTrue(any("bilibili" in r["trigger"] for r in results))

    def test_no_match(self):
        from memory.memory_system import MemorySystem
        ms = MemorySystem()
        results = ms.get_triggered_memories("今天天气怎么样")
        bilibili_matches = [r for r in results if "bilibili" in r.get("trigger", "")]
        self.assertEqual(len(bilibili_matches), 0)


@unittest.skipUnless(_HAS_HTTPX, "需要 httpx 依赖")
class TestCheckToolHadResult(unittest.TestCase):
    """验证 _check_tool_had_result 兼容新旧格式"""

    def setUp(self):
        from core.conversation import Conversation
        self.conv = Conversation.__new__(Conversation)
        self.conv.tool_log = []
        self.conv._token_usage = []

    def test_toolresult_success(self):
        from tools.tool_utils import ToolResult
        r = ToolResult.ok({"data": "test"})
        self.assertTrue(self.conv._check_tool_had_result(r))

    def test_toolresult_fail(self):
        from tools.tool_utils import ToolResult
        r = ToolResult.fail("error", "E_TEST")
        self.assertFalse(self.conv._check_tool_had_result(r))

    def test_old_format_success(self):
        old = json.dumps({"success": True, "data": "test"})
        self.assertTrue(self.conv._check_tool_had_result(old))

    def test_old_format_error(self):
        old = json.dumps({"error": "something failed"})
        self.assertFalse(self.conv._check_tool_had_result(old))

    def test_old_format_results(self):
        old = json.dumps({"results": [1, 2, 3]})
        self.assertTrue(self.conv._check_tool_had_result(old))

    def test_empty_string(self):
        self.assertFalse(self.conv._check_tool_had_result(""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
