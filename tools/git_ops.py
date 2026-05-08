"""
YI-Agent V4 Git 工具集
提供安全的版本控制操作，内置测试门禁。
使用 GitPython 替代 subprocess，所有操作通过 ThreadPoolExecutor 避免阻塞事件循环。
"""
import os
import json
import asyncio
import concurrent.futures
from pathlib import Path
from typing import Optional, List

import git
from git.exc import GitCommandError, InvalidGitRepositoryError


# ---- 内部辅助 ----

def _get_repo(cwd: str = None) -> git.Repo:
    """获取当前项目的 Git 仓库实例"""
    try:
        if cwd:
            return git.Repo(cwd, search_parent_directories=True)
        return git.Repo(search_parent_directories=True)
    except InvalidGitRepositoryError:
        raise RuntimeError(f"未找到 Git 仓库: {cwd or '当前目录'}")


def _get_project_root() -> Path:
    """项目根目录（仓库根）"""
    return Path(_get_repo().working_tree_dir)


def _read_test_result(cwd: str = None) -> Optional[dict]:
    """读取最近一次测试结果（优先从 cwd 项目目录读取）"""
    import time as _time
    if cwd:
        result_file = Path(cwd) / ".last_test_result.json"
    else:
        result_file = _get_project_root() / ".last_test_result.json"
    if not result_file.exists():
        return None
    try:
        with open(result_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # v4.2: 测试结果 30 分钟过期
        ts = data.get("timestamp_epoch", 0)
        if ts and _time.time() - ts > 1800:
            return None  # 过期视为无结果
        return data
    except Exception:
        return None


def _save_test_result(command: str, returncode: int, output: str, cwd: str = None):
    """如果命令包含 pytest，自动保存测试结果（写入项目目录）"""
    if "pytest" not in command:
        return
    from datetime import datetime
    result = {
        "timestamp": datetime.now().isoformat(),
        "timestamp_epoch": datetime.now().timestamp(),
        "command": command,
        "all_passed": returncode == 0,
        "exit_code": returncode,
        "output_tail": output[-500:]  # 仅保留最后500字符
    }
    if cwd:
        test_file = Path(cwd) / ".last_test_result.json"
    else:
        test_file = _get_project_root() / ".last_test_result.json"
    try:
        with open(test_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ---- 同步核心逻辑 ----

def _sync_git_status(cwd: str = None) -> dict:
    repo = _get_repo(cwd)
    try:
        branch = repo.active_branch.name
    except TypeError:
        branch = "HEAD detached"
    changed = [item.a_path for item in repo.index.diff(None)]       # 工作区 vs 暂存区
    staged = [item.a_path for item in repo.index.diff("HEAD")]      # 暂存区 vs HEAD
    untracked = repo.untracked_files
    return {
        "success": True,
        "branch": branch,
        "changed": list(set(changed)),
        "staged": list(set(staged)),
        "untracked": list(untracked)
    }


def _sync_git_diff(file_path: str = None, cwd: str = None) -> dict:
    repo = _get_repo(cwd)
    try:
        diff_text = repo.git.diff(file_path) if file_path else repo.git.diff()
        max_len = 2000
        if len(diff_text) > max_len:
            diff_text = diff_text[:max_len] + "\n... (diff truncated)"
        return {"success": True, "diff": diff_text}
    except GitCommandError as e:
        return {"success": False, "error": str(e)}


def _sync_git_add(file_paths: List[str], cwd: str = None) -> dict:
    repo = _get_repo(cwd)
    root = Path(repo.working_tree_dir)
    # 安全检查：路径穿越 + 敏感文件
    sensitive_files = {".env", "credentials.json", "secret", "token", ".env.local"}
    for fp in file_paths:
        abs_path = (root / fp).resolve()
        if not str(abs_path).startswith(str(root)):
            return {"success": False, "error": f"文件 {fp} 不在项目目录内"}
        if fp.lower() in sensitive_files:
            return {"success": False, "error": f"禁止添加敏感文件: {fp}"}
    try:
        repo.index.add(file_paths)
        return {"success": True, "added": file_paths}
    except GitCommandError as e:
        return {"success": False, "error": str(e)}


def _sync_git_commit(message: str, cwd: str = None) -> dict:
    repo = _get_repo(cwd)
    if not message or len(message) > 200:
        return {"success": False, "error": "提交信息长度必须在1-200字符"}
    if not repo.index.diff("HEAD") and not repo.untracked_files:
        return {"success": False, "error": "没有需要提交的更改"}
    try:
        commit = repo.index.commit(message)
        return {"success": True, "hash": commit.hexsha[:7], "message": message}
    except GitCommandError as e:
        return {"success": False, "error": str(e)}


def _sync_git_push(branch: str = "main", force_skip_test: bool = False, cwd: str = None) -> dict:
    """推送（包含测试门禁）— P0 修复：无测试结果时默认拒绝"""
    if not force_skip_test:
        test = _read_test_result(cwd=cwd)
        if not test:
            # P0 修复：无测试结果 = 拒绝推送（之前部分路径会放行）
            return {
                "success": False,
                "error": "⛔ 没有找到有效的测试结果，推送被门禁拦截。请先运行 pytest 且全部通过后再推送。",
                "blocked_by_test": True,
                "hint": "运行 `pytest tests/ -v` 确认全部通过后重试。"
            }
        if not test.get("all_passed"):
            return {
                "success": False,
                "error": f"⛔ 测试未通过（exit_code={test.get('exit_code', '?')}），推送被禁止。",
                "blocked_by_test": True,
                "last_test_output": test.get("output_tail", "")[:300],
            }
    repo = _get_repo(cwd)
    try:
        origin = repo.remote(name="origin")
        origin.push(branch)
        return {"success": True, "branch": branch}
    except GitCommandError as e:
        return {"success": False, "error": str(e)}


def _sync_git_restore(file_paths: Optional[List[str]] = None, cwd: str = None) -> dict:
    """回滚工作区文件到 HEAD 状态"""
    repo = _get_repo(cwd)
    try:
        if file_paths:
            repo.git.checkout("--", *file_paths)
        else:
            repo.git.checkout("--", ".")
        return {"success": True, "restored": file_paths or "all"}
    except GitCommandError as e:
        return {"success": False, "error": str(e)}


# ---- 同步包装器（对外暴露，和 system_tools 保持一致） ----

def _run_in_executor(fn, *args, timeout: int = 30):
    """在 ThreadPoolExecutor 中运行同步函数，兼容 async 上下文"""
    try:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(fn, *args).result(timeout=timeout)
    except RuntimeError:
        return fn(*args)


def git_status(cwd: str = None) -> dict:
    return _run_in_executor(_sync_git_status, cwd)


def git_diff(file_path: str = None, cwd: str = None) -> dict:
    return _run_in_executor(_sync_git_diff, file_path, cwd)


def git_add(file_paths: List[str], cwd: str = None) -> dict:
    return _run_in_executor(_sync_git_add, file_paths, cwd)


def git_commit(message: str, cwd: str = None) -> dict:
    return _run_in_executor(_sync_git_commit, message, cwd)


def git_push(branch: str = "main", cwd: str = None) -> dict:
    # force_skip_test 不暴露给 LLM，此处固定 False
    return _run_in_executor(_sync_git_push, branch, False, cwd)


def git_restore(file_paths: Optional[List[str]] = None, cwd: str = None) -> dict:
    """回滚指定文件或全部工作区更改"""
    return _run_in_executor(_sync_git_restore, file_paths, cwd)


def git_last_test() -> dict:
    """查看最近一次测试结果"""
    test = _read_test_result()
    if not test:
        return {"success": False, "error": "没有找到测试结果"}
    return {"success": True, "test_result": test}
