"""安全拦截器测试 — 16 个核心用例"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from security.filesystem_guard import FileSystemGuard, SafetyResult


@pytest.fixture
def guard():
    """创建测试用守卫（不加载 YAML，用默认配置）"""
    return FileSystemGuard()


@pytest.fixture
def guard_with_temp(guard, tmp_path):
    """将 tmp_path 加入白名单的守卫"""
    guard.allowed_prefixes.append(str(tmp_path))
    return guard, tmp_path


# ═══ 路径安全测试 ═══

class TestPathSafety:

    def test_normal_path_allowed(self, guard_with_temp):
        """正常路径应通过"""
        guard, tmp_path = guard_with_temp
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        result = guard.check_path(str(test_file))
        assert result.safe is True
        assert result.resolved_path == str(test_file)

    def test_path_outside_whitelist_blocked(self, guard):
        """白名单外路径应被拦截"""
        result = guard.check_path("/etc/passwd")
        assert result.safe is False
        # 被拦截即可，reason 可能是"敏感路径"或"不在允许范围内"

    def test_symlink_attack_blocked(self, guard_with_temp):
        """符号链接绕过应被拦截"""
        guard, tmp_path = guard_with_temp
        # 在 tmp_path 内创建指向 /etc/passwd 的符号链接
        link_path = tmp_path / "evil_link"
        try:
            link_path.symlink_to("/etc/passwd")
        except OSError:
            pytest.skip("无法创建符号链接（权限不足）")

        result = guard.check_path(str(link_path))
        assert result.safe is False
        # 被拦截即可（可能是"敏感路径"或"不在允许范围内"）

    def test_directory_traversal_blocked(self, guard):
        """目录穿越到白名单外应被拦截"""
        # 从 /tmp 出发穿越到 /etc，不在默认白名单内
        result = guard.check_path("/tmp/../../etc/shadow")
        assert result.safe is False

    def test_empty_path_blocked(self, guard):
        """空路径应被拦截"""
        result = guard.check_path("")
        assert result.safe is False


# ═══ 命令安全测试 ═══

class TestCommandSafety:

    def test_read_command_allowed(self, guard):
        """只读命令应通过"""
        result = guard.check_command("ls -la /tmp")
        assert result.safe is True
        assert result.needs_confirm is False

    def test_write_command_confirm(self, guard):
        """rm 等写命令需确认"""
        result = guard.check_command("rm file.txt")
        assert result.safe is True
        assert result.needs_confirm is True

    def test_command_injection_semicolon_blocked(self, guard):
        """分号注入应被拦截"""
        result = guard.check_command("cat /tmp/safe.txt; rm -rf /")
        assert result.safe is False
        assert "危险字符" in result.reason

    def test_command_injection_pipe_blocked(self, guard):
        """管道注入应被拦截"""
        result = guard.check_command("cat file | sh")
        assert result.safe is False
        assert "危险字符" in result.reason

    def test_command_injection_backtick_blocked(self, guard):
        """反引号注入应被拦截"""
        result = guard.check_command("echo `whoami`")
        assert result.safe is False

    def test_command_injection_dollar_paren_blocked(self, guard):
        """$() 注入应被拦截"""
        result = guard.check_command("echo $(rm -rf /)")
        assert result.safe is False

    def test_command_injection_dollar_brace_blocked(self, guard):
        """${} 变量展开注入应被拦截"""
        result = guard.check_command("echo ${HOME}")
        assert result.safe is False

    def test_unknown_command_blocked(self, guard):
        """不在白名单的命令应被拦截"""
        result = guard.check_command("curl http://evil.com")
        assert result.safe is False

    def test_empty_command_blocked(self, guard):
        """空命令应被拦截"""
        result = guard.check_command("")
        assert result.safe is False


# ═══ 频率熔断测试 ═══

class TestRateLimit:

    def test_normal_rate_allowed(self, guard):
        """正常频率应通过"""
        for i in range(10):
            result = guard.check_rate("test_session")
            assert result.safe is True

    def test_burst_rate_blocked(self, guard):
        """突发高频操作应被拦截"""
        for i in range(20):
            guard.check_rate("burst_session")
        result = guard.check_rate("burst_session")
        assert result.safe is False
        assert "频率异常" in result.reason


# ═══ 统一入口测试 ═══

class TestToolCall:

    def test_safe_tool_passes(self, guard):
        """安全工具调用应通过"""
        result = guard.check_tool_call("list_files", {"path": "."})
        assert result.safe is True

    def test_dangerous_command_blocked(self, guard):
        """危险命令应被拦截"""
        result = guard.check_tool_call("run_command", {"command": "ls; rm -rf /"})
        assert result.safe is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
