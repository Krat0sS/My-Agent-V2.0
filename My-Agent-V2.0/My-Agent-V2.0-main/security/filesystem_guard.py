# -*- coding: utf-8 -*-
"""
文件系统安全守卫 — Phase 3 增强版

改进：
1. git 子命令精确分类（git status / git push / git reset 等）
2. 审计日志持久化（SQLite）
3. 频率熔断 + 审计日志 API
"""

import os
import time
import sqlite3
import threading
import collections
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field


# ═══ 命令三级分类 ═══

# 只读命令（直接放行）
_DEFAULT_READ_ONLY = {
    "ls", "stat", "find", "du", "df", "file", "cat", "head", "tail",
    "tree", "wc", "md5sum", "sha256sum", "pwd", "whoami", "which",
    "echo", "date", "env", "printenv",
    # Windows
    "dir", "type", "where", "ver", "systeminfo", "tasklist",
    "ipconfig", "ping", "tracert", "nslookup", "hostname",
}

# 写入命令（放行 + 日志）
_DEFAULT_WRITE = {
    "mv", "cp", "rsync", "mkdir", "touch", "ln",
    "tar", "zip", "unzip", "diff", "tee",
    # Windows
    "xcopy", "robocopy", "ren", "rename",
    # 开发工具（放行，不拦截）
    "python", "python3", "pip", "pip3", "node", "npm", "npx",
    "playwright", "pytest", "git",
    # 系统启动命令
    "start", "open", "xdg-open", "code", "notepad",
    # 包管理
    "apt", "apt-get", "yum", "brew", "conda",
}

# 危险命令（需确认）
_DEFAULT_WRITE_CONFIRM = {
    "rm", "rmdir", "chmod", "chown", "chgrp",
}

# git 子命令分类
_GIT_READ_ONLY = {"status", "log", "diff", "show", "branch", "tag", "remote", "describe"}
_GIT_WRITE = {"add", "commit", "restore", "stash", "checkout", "merge", "rebase", "cherry-pick",
              "clone", "fetch", "pull", "init", "mv", "rm", "push", "reset", "clean", "revert"}
_GIT_DANGEROUS = set()  # 前端权限控制，后端不再额外拦截

# 阻断字符（命令注入检测）
_DEFAULT_BLOCKED_CHARS = {";", "|", "&", "`", "$(", "${", "\n", "\r"}

# 路径白名单
_DEFAULT_ALLOWED_PREFIXES = [
    os.path.expanduser("~"),
    "/tmp",
]


@dataclass
class SafetyResult:
    """安全检查结果"""
    safe: bool = True
    reason: str = ""
    needs_confirm: bool = False
    risk_level: str = "none"  # none / low / medium / high
    resolved_path: str = ""
    details: dict = field(default_factory=dict)


class FileSystemGuard:
    """
    文件系统安全守卫

    使用：
        guard = FileSystemGuard()
        result = guard.check_command("git push origin main")
        if result.needs_confirm:
            print(f"需要确认: {result.reason}")
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._op_timestamps: dict = {}

        # 命令分类
        self.read_only = set(_DEFAULT_READ_ONLY)
        self.write = set(_DEFAULT_WRITE)
        self.write_confirm = set(_DEFAULT_WRITE_CONFIRM)
        self.blocked_chars = set(_DEFAULT_BLOCKED_CHARS)

        # 路径白名单
        self.allowed_prefixes = list(_DEFAULT_ALLOWED_PREFIXES)

        # 从 config 读取
        try:
            import config as _cfg
            self.rate_window = getattr(_cfg, 'SECURITY_RATE_WINDOW', 30)
            self.rate_max_ops = getattr(_cfg, 'SECURITY_RATE_MAX_OPS', 20)
            self._enabled = getattr(_cfg, 'SECURITY_ENABLED', True)
            # 自定义允许路径
            extra_paths = getattr(_cfg, 'ALLOWED_PATHS', '')
            if extra_paths:
                for p in extra_paths.split(','):
                    p = p.strip()
                    if p and p not in self.allowed_prefixes:
                        self.allowed_prefixes.append(p)
        except ImportError:
            self.rate_window = 30
            self.rate_max_ops = 20
            self._enabled = True

        # 自动追加用户主目录和 cwd
        for p in [os.path.expanduser("~"), os.getcwd()]:
            real_p = os.path.realpath(p)
            if real_p not in [os.path.realpath(x) for x in self.allowed_prefixes]:
                if os.path.exists(real_p):
                    self.allowed_prefixes.append(real_p)

        # 审计日志（SQLite 持久化）
        self._db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'audit_log.db')
        self._init_audit_db()

    # ═══ 审计日志持久化 ═══

    def _init_audit_db(self):
        """初始化审计日志数据库"""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                session_id TEXT DEFAULT '',
                tool TEXT DEFAULT '',
                command TEXT DEFAULT '',
                result TEXT DEFAULT '',
                risk_level TEXT DEFAULT '',
                reason TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp)")
        conn.commit()
        conn.close()

    def _write_audit(self, tool: str, command: str, result: str,
                     risk_level: str = "", reason: str = "", session_id: str = ""):
        """写入审计日志"""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT INTO audit_log (timestamp, session_id, tool, command, result, risk_level, reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), session_id, tool, command[:500], result, risk_level, reason)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass  # 审计写入失败不影响主流程

    def get_audit_log(self, limit: int = 100, result_filter: str = None) -> list:
        """获取审计日志"""
        conn = sqlite3.connect(self._db_path)
        if result_filter:
            rows = conn.execute(
                "SELECT timestamp, session_id, tool, command, result, risk_level, reason "
                "FROM audit_log WHERE result = ? ORDER BY id DESC LIMIT ?",
                (result_filter, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT timestamp, session_id, tool, command, result, risk_level, reason "
                "FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()

        return [
            {
                "time": datetime.fromtimestamp(r[0]).strftime("%Y-%m-%d %H:%M:%S"),
                "session_id": r[1],
                "tool": r[2],
                "command": r[3],
                "result": r[4],
                "risk": r[5],
                "reason": r[6],
            }
            for r in rows
        ]

    def get_audit_stats(self) -> dict:
        """获取审计统计"""
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN result='passed' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN result='confirmed' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN result='blocked' THEN 1 ELSE 0 END) "
            "FROM audit_log"
        ).fetchone()
        conn.close()
        return {
            "total": row[0] or 0,
            "passed": row[1] or 0,
            "confirmed": row[2] or 0,
            "blocked": row[3] or 0,
        }

    def clear_audit_log(self):
        """清空审计日志"""
        conn = sqlite3.connect(self._db_path)
        conn.execute("DELETE FROM audit_log")
        conn.commit()
        conn.close()

    # ═══ 路径安全检查 ═══

    def check_path(self, path: str) -> SafetyResult:
        """路径安全检查"""
        if not self._enabled:
            return SafetyResult(safe=True)

        if not path:
            return SafetyResult(safe=False, reason="路径为空")

        expanded = os.path.expanduser(path)
        try:
            resolved = os.path.realpath(expanded)
        except OSError:
            resolved = expanded

        # 敏感路径硬编码拒绝（精确匹配路径组件）
        denied_exact = {"/etc/passwd", "/etc/shadow"}
        denied_components = {"authorized_keys"}
        path_parts = set(Path(resolved).parts)

        for d in denied_exact:
            if resolved == d or resolved.startswith(d + os.sep):
                return self._audit_result(
                    SafetyResult(safe=False, reason=f"敏感路径: {resolved}", risk_level="high"),
                    tool="path_check", command=path,
                )
        for d in denied_components:
            if d in path_parts:
                return self._audit_result(
                    SafetyResult(safe=False, reason=f"敏感路径: {resolved}", risk_level="high"),
                    tool="path_check", command=path,
                )

        # 允许前缀检查
        for prefix in self.allowed_prefixes:
            real_prefix = os.path.realpath(prefix)
            if resolved.startswith(real_prefix + os.sep) or resolved == real_prefix:
                return SafetyResult(safe=True, resolved_path=resolved)

        return self._audit_result(
            SafetyResult(safe=False, reason=f"路径不在允许范围内: {resolved}", risk_level="high"),
            tool="path_check", command=path,
        )

    # ═══ 命令安全检查 ═══

    def check_command(self, command: str) -> SafetyResult:
        """命令安全检查（三级分类 + git 子命令）"""
        if not self._enabled:
            return SafetyResult(safe=True)

        if not command or not command.strip():
            return SafetyResult(safe=False, reason="命令为空")

        # 阻断字符检测（命令注入）
        for char in self.blocked_chars:
            if char in command:
                return self._audit_result(
                    SafetyResult(safe=False, reason=f"包含危险字符: {repr(char)}", risk_level="high"),
                    tool="cmd_check", command=command,
                )

        # 提取命令名（支持引号包裹的路径）
        import shlex
        try:
            parts = shlex.split(command.strip())
        except ValueError:
            parts = command.strip().split()
        cmd = parts[0] if parts else ""
        cmd_base = os.path.basename(cmd).lower()
        # 去掉 .exe 后缀（Windows）
        if cmd_base.endswith(".exe"):
            cmd_base = cmd_base[:-4]

        # git 子命令特殊处理
        if cmd_base in ("git", "git.exe") and len(parts) >= 2:
            subcmd = parts[1].lower()
            return self._check_git_subcommand(subcmd, command)

        # 普通命令分类
        if cmd_base in self.read_only:
            return SafetyResult(safe=True, risk_level="none")
        if cmd_base in self.write_confirm:
            return self._audit_result(
                SafetyResult(safe=True, needs_confirm=True, risk_level="high"),
                tool=cmd_base, command=command,
            )
        if cmd_base in self.write:
            return SafetyResult(safe=True, risk_level="low")

        # 未分类命令 → 阻止
        return self._audit_result(
            SafetyResult(safe=False, reason=f"未知命令: {cmd_base}", risk_level="high"),
            tool=cmd_base, command=command,
        )

    def _check_git_subcommand(self, subcmd: str, command: str) -> SafetyResult:
        """git 子命令分类"""
        if subcmd in _GIT_READ_ONLY:
            return SafetyResult(safe=True, risk_level="none")
        if subcmd in _GIT_WRITE:
            return SafetyResult(safe=True, risk_level="low")
        if subcmd in _GIT_DANGEROUS:
            # git push --force 额外风险
            if subcmd == "push" and ("--force" in command or "-f" in command):
                return self._audit_result(
                    SafetyResult(safe=True, needs_confirm=True, risk_level="high",
                                 reason="git push --force 可能覆盖远程提交"),
                    tool=f"git-{subcmd}", command=command,
                )
            return self._audit_result(
                SafetyResult(safe=True, needs_confirm=True, risk_level="high"),
                tool=f"git-{subcmd}", command=command,
            )

        # 未知 git 子命令 → 需要确认
        return self._audit_result(
            SafetyResult(safe=True, needs_confirm=True, risk_level="medium"),
            tool=f"git-{subcmd}", command=command,
        )

    # ═══ 频率熔断 ═══

    def check_rate(self, session_id: str = "default") -> SafetyResult:
        """检查操作频率（滑动窗口限流）"""
        if not self._enabled:
            return SafetyResult(safe=True)

        now = time.time()
        with self._lock:
            if session_id not in self._op_timestamps:
                self._op_timestamps[session_id] = []

            timestamps = self._op_timestamps[session_id]
            cutoff = now - self.rate_window
            self._op_timestamps[session_id] = [t for t in timestamps if t > cutoff]

            if len(self._op_timestamps[session_id]) >= self.rate_max_ops:
                return SafetyResult(
                    safe=False,
                    reason=f"操作频率异常: {self.rate_window}秒内{len(self._op_timestamps[session_id])}次操作",
                    risk_level="high",
                )

            self._op_timestamps[session_id].append(now)
            return SafetyResult(safe=True)

    # ═══ 统一入口 ═══

    def check_tool_call(self, tool_name: str, arguments: dict,
                        session_id: str = "default") -> SafetyResult:
        """统一安全检查入口"""
        if not self._enabled:
            return SafetyResult(safe=True)

        # 频率检查
        rate = self.check_rate(session_id)
        if not rate.safe:
            self._write_audit(tool_name, str(arguments)[:200], "blocked",
                              rate.risk_level, rate.reason, session_id)
            return rate

        # 工具特定检查
        result = SafetyResult(safe=True)
        if tool_name in ("run_command", "run_command_confirmed"):
            result = self.check_command(arguments.get("command", ""))
        elif tool_name in ("read_file", "write_file", "edit_file", "move_file"):
            result = self.check_path(arguments.get("path", ""))
        elif tool_name in ("scan_files", "find_files", "list_files"):
            result = self.check_path(arguments.get("path", "."))

        # 写入审计
        audit_result = "blocked" if not result.safe else "confirmed" if result.needs_confirm else "passed"
        self._write_audit(tool_name, str(arguments)[:200], audit_result,
                          result.risk_level, result.reason, session_id)

        return result

    # ═══ GUI 操作确认 ═══

    def check_gui_operation(self, func_name: str, args: dict) -> dict:
        """桌面/浏览器操作确认门控"""
        if not self._enabled:
            return {"needs_confirm": False}
        dangerous_gui = {"ab_click", "ab_fill", "ab_type", "ab_press",
                         "ab_dblclick", "ab_check", "ab_uncheck", "ab_select"}
        if func_name in dangerous_gui:
            return {
                "needs_confirm": True,
                "confirm_message": f"即将执行 GUI 操作: {func_name}",
            }
        return {"needs_confirm": False}

    def _audit_result(self, result: SafetyResult, tool: str, command: str) -> SafetyResult:
        """写入审计日志并返回结果"""
        audit_result = "blocked" if not result.safe else "confirmed" if result.needs_confirm else "passed"
        self._write_audit(tool, command[:500], audit_result, result.risk_level, result.reason)
        return result


# ═══ 全局单例 ═══
guard = FileSystemGuard()
