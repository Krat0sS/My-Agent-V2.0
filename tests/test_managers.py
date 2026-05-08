"""manage 层测试 — 工具管理器 + 技能管理器 + 记忆管理器"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══ 工具管理器测试 ═══

class TestToolManager:

    @pytest.fixture(autouse=True)
    def setup(self):
        from tools.registry import ToolRegistry, ToolDefinition
        from manage.tool_manager import ToolManager
        self.registry = ToolRegistry()
        # 注册几个测试工具
        self.registry.register(
            name="read_file", description="读取文件",
            schema={}, handler=lambda: None,
            category="file", risk_level="low",
        )
        self.registry.register(
            name="write_file", description="写入文件",
            schema={}, handler=lambda: None,
            category="file", risk_level="medium",
        )
        self.registry.register(
            name="run_command", description="执行命令",
            schema={}, handler=lambda: None,
            category="system", risk_level="high",
        )
        self.mgr = ToolManager(self.registry)

    def test_list_by_category(self):
        result = self.mgr.list_by_category()
        assert result["success"] is True
        assert "file" in result["categories"]
        assert "system" in result["categories"]
        assert len(result["categories"]["file"]) == 2

    def test_search(self):
        result = self.mgr.search("file")
        assert result["success"] is True
        assert result["count"] == 2  # read_file, write_file

    def test_search_no_match(self):
        result = self.mgr.search("nonexistent")
        assert result["success"] is True
        assert result["count"] == 0

    def test_get_tool(self):
        result = self.mgr.get("read_file")
        assert result["success"] is True
        assert result["tool"]["name"] == "read_file"
        assert result["tool"]["risk_level"] == "low"

    def test_get_nonexistent(self):
        result = self.mgr.get("no_such_tool")
        assert result["success"] is False

    def test_toggle_disable(self):
        result = self.mgr.toggle("read_file", False)
        assert result["success"] is True
        td = self.registry.get("read_file")
        assert td.is_available() is False

    def test_toggle_enable(self):
        self.mgr.toggle("read_file", False)
        result = self.mgr.toggle("read_file", True)
        assert result["success"] is True
        td = self.registry.get("read_file")
        assert td.is_available() is True

    def test_batch_toggle(self):
        result = self.mgr.batch_toggle(["read_file", "write_file"], False)
        assert result["succeeded"] == 2
        assert self.registry.get("read_file").is_available() is False
        assert self.registry.get("write_file").is_available() is False

    def test_reset(self):
        self.mgr.toggle("read_file", False)
        result = self.mgr.reset("read_file")
        assert result["success"] is True
        # reset 后应恢复为默认（available）
        assert self.registry.get("read_file").is_available() is True

    def test_stats(self):
        result = self.mgr.get_stats()
        assert result["success"] is True
        assert result["total"] == 3
        assert result["by_risk"]["low"] == 1
        assert result["by_risk"]["high"] == 1


# ═══ 技能管理器测试 ═══

class TestSkillManager:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from manage.skill_manager import SkillManager
        # 创建测试技能目录
        skill_dir = tmp_path / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# test-skill\n\n这是一个测试技能。")
        self.mgr = SkillManager(str(tmp_path / "skills"))
        self.tmp_path = tmp_path

    def test_list_skills(self):
        result = self.mgr.list_skills()
        assert result["success"] is True
        assert result["count"] == 1
        assert result["skills"][0]["name"] == "test-skill"

    def test_read_skill(self):
        result = self.mgr.read_skill("test-skill")
        assert result["success"] is True
        assert "测试技能" in result["content"]

    def test_read_nonexistent(self):
        result = self.mgr.read_skill("no-such-skill")
        assert result["success"] is False

    def test_create_skill(self):
        result = self.mgr.create_skill("new-skill", "新技能描述")
        assert result["success"] is True
        # 验证文件存在
        skill_md = self.tmp_path / "skills" / "new-skill" / "SKILL.md"
        assert skill_md.exists()
        assert "new-skill" in skill_md.read_text()

    def test_create_duplicate(self):
        result = self.mgr.create_skill("test-skill")
        assert result["success"] is False
        assert "已存在" in result["error"]

    def test_update_skill(self):
        result = self.mgr.update_skill("test-skill", "# 更新后的内容\n\n新内容。")
        assert result["success"] is True
        assert "backup" in result
        # 验证内容已更新
        read_result = self.mgr.read_skill("test-skill")
        assert "更新后的内容" in read_result["content"]

    def test_delete_skill_with_confirm(self):
        result = self.mgr.delete_skill("test-skill", confirm=True)
        assert result["success"] is True
        assert "回收站" in result["message"]
        # 原目录应不存在
        assert not (self.tmp_path / "skills" / "test-skill").exists()

    def test_delete_skill_needs_confirm(self):
        result = self.mgr.delete_skill("test-skill", confirm=False)
        assert result["needs_confirm"] is True

    def test_validate_skill(self):
        result = self.mgr.validate_skill("test-skill")
        assert result["success"] is True
        assert result["valid"] is True


# ═══ 记忆管理器测试 ═══

class TestMemoryManager:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from manage.memory_manager import MemoryManager
        # 创建测试记忆目录
        memory_dir = tmp_path / "workspace" / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "2026-05-05.md").write_text("# 2026-05-05\n\n今天做了安全硬内核。")
        (memory_dir / "2026-05-04.md").write_text("# 2026-05-04\n\n项目启动。")
        (tmp_path / "workspace" / "MEMORY.md").write_text("# MEMORY.md\n\n长期记忆：用户 Krat0sS。")
        self.mgr = MemoryManager(str(tmp_path / "workspace"))
        self.tmp_path = tmp_path

    def test_list_daily(self):
        result = self.mgr.list_daily_memories()
        assert result["success"] is True
        assert result["count"] == 2

    def test_read_memory(self):
        result = self.mgr.read_memory("2026-05-05.md")
        assert result["success"] is True
        assert "安全硬内核" in result["content"]

    def test_read_long_term(self):
        result = self.mgr.read_memory("MEMORY.md")
        assert result["success"] is True
        assert "Krat0sS" in result["content"]

    def test_search(self):
        result = self.mgr.search_memories("Krat0sS")
        assert result["success"] is True
        assert result["file_count"] >= 1

    def test_search_no_match(self):
        result = self.mgr.search_memories("完全不存在的关键词xyz")
        assert result["success"] is True
        assert result["file_count"] == 0

    def test_delete_daily(self):
        result = self.mgr.delete_memory("2026-05-04.md", confirm=True)
        assert result["success"] is True
        # 原文件应不存在
        assert not (self.tmp_path / "workspace" / "memory" / "2026-05-04.md").exists()

    def test_delete_memory_md_blocked(self):
        result = self.mgr.delete_memory("MEMORY.md", confirm=True)
        assert result["success"] is False
        assert "不能删除" in result["error"]

    def test_delete_needs_confirm(self):
        result = self.mgr.delete_memory("2026-05-05.md", confirm=False)
        assert result["needs_confirm"] is True

    def test_stats(self):
        result = self.mgr.get_stats()
        assert result["success"] is True
        assert result["daily_count"] == 2
        assert result["memory_md_size"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
