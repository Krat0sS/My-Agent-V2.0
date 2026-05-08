"""命令执行工具 — asyncio.subprocess 版本"""
import json
import asyncio
from datetime import datetime
from pathlib import Path
import config


def _is_git_push(command: str) -> bool:
    """检测命令是否是 git push（支持各种写法）"""
    cmd = command.strip().lower()
    # 直接 git push
    if cmd.startswith("git push"):
        return True
    # git remote push / git push origin main 等
    if "git" in cmd and "push" in cmd:
        # 排除 git push --help 等查询命令
        if "--help" in cmd or "-h" in cmd:
            return False
        return True
    return False


def _check_git_push_gate(cwd: str = None) -> str | None:
    """检查测试门禁。返回 None 表示放行，返回 JSON 字符串表示拦截。
    P0 修复：无测试结果或读取异常 = 拒绝（之前会降级放行）。
    """
    import time as _time
    if cwd:
        result_file = Path(cwd) / ".last_test_result.json"
    else:
        result_file = Path(__file__).resolve().parent.parent / ".last_test_result.json"

    if not result_file.exists():
        return json.dumps({
            "blocked_by_test": True,
            "error": "⛔ 没有找到测试结果，git push 被门禁拦截。请先运行 pytest。",
            "hint": "请先运行 `pytest tests/ -v`，测试全部通过后才能 push。"
        }, ensure_ascii=False)

    try:
        with open(result_file, "r", encoding="utf-8") as f:
            test = json.load(f)
    except Exception:
        # P0 修复：读取失败也拦截（之前是 pass 降级放行）
        return json.dumps({
            "blocked_by_test": True,
            "error": "⛔ 测试结果文件损坏或无法读取，git push 被门禁拦截。",
            "hint": "请重新运行 pytest 后再推送。"
        }, ensure_ascii=False)

    # v4.2: 测试结果 30 分钟过期
    ts = test.get("timestamp_epoch", 0)
    if ts and _time.time() - ts > 1800:
        return json.dumps({
            "blocked_by_test": True,
            "error": "⛔ 测试结果已过期（>30分钟），请重新运行测试。",
            "hint": "请重新执行 pytest 后再推送。"
        }, ensure_ascii=False)

    if not test.get("all_passed"):
        return json.dumps({
            "blocked_by_test": True,
            "error": "⛔ 测试未通过，git push 被门禁拦截。",
            "last_test": {
                "command": test.get("command", ""),
                "exit_code": test.get("exit_code", -1),
                "output_tail": test.get("output_tail", "")[:300],
            }
        }, ensure_ascii=False)

    return None  # 测试通过，放行


def _save_test_result_if_pytest(command: str, returncode: int, output: str, cwd: str = None):
    """如果命令包含 pytest，自动保存测试结果到项目目录（供 git_push 门禁使用）"""
    if "pytest" not in command:
        return
    result = {
        "timestamp": datetime.now().isoformat(),
        "timestamp_epoch": datetime.now().timestamp(),
        "command": command,
        "all_passed": returncode == 0,
        "exit_code": returncode,
        "output_tail": output[-500:]  # 仅保留最后500字符
    }
    # 优先写入 cwd 对应的项目目录（与 git_ops.py 的 _read_test_result 路径一致）
    if cwd:
        test_file = Path(cwd) / ".last_test_result.json"
    else:
        test_file = Path(__file__).resolve().parent.parent / ".last_test_result.json"
    try:
        with open(test_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


async def run_command_async(command: str, cwd: str = None, timeout: int = 30) -> str:
    """
    异步执行 shell 命令。
    用 asyncio.subprocess 替代 subprocess.run，支持取消。
    """
    # 安全检查：黑名单
    for blocked in config.BLOCKED_COMMANDS:
        if blocked in command:
            return json.dumps({"error": f"危险命令被阻止: {blocked}"})

    # P1: git push 门禁 — 绕过 git_push 工具的 run_command("git push") 也要拦截
    if _is_git_push(command):
        gate_result = _check_git_push_gate(cwd=cwd)
        if gate_result is not None:
            return gate_result

    # 安全检查：确认列表
    needs_confirm = False
    for prefix in config.CONFIRM_COMMANDS:
        if command.strip().startswith(prefix) or f" {prefix}" in command:
            needs_confirm = True
            break

    if needs_confirm:
        return json.dumps({
            "needs_confirm": True,
            "command": command,
            "warning": f"⚠️ 该命令可能修改系统状态，是否确认执行？\n$ {command}"
        })

    return await _exec_subprocess(command, cwd, timeout)


async def run_command_confirmed_async(command: str, cwd: str = None, timeout: int = 30) -> str:
    """异步执行已确认的命令（跳过确认检查）"""
    for blocked in config.BLOCKED_COMMANDS:
        if blocked in command:
            return json.dumps({"error": f"危险命令被阻止: {blocked}"})
    # P1: git push 门禁 — confirmed 版本也不能绕过
    if _is_git_push(command):
        gate_result = _check_git_push_gate(cwd=cwd)
        if gate_result is not None:
            return gate_result
    return await _exec_subprocess(command, cwd, timeout)


async def _exec_subprocess(command: str, cwd: str = None, timeout: int = 30) -> str:
    """底层 asyncio.subprocess 执行"""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            # 超时：杀掉进程组
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            return json.dumps({
                "error": f"命令超时 ({timeout}s)",
                "command": command,
                "hint": "进程已被终止。"
            })

        output_str = stdout.decode(errors="replace")[:10000]

        # 自动保存 pytest 测试结果（供 git_push 门禁使用）
        _save_test_result_if_pytest(command, proc.returncode, output_str, cwd=cwd)

        return json.dumps({
            "stdout": output_str,
            "stderr": stderr.decode(errors="replace")[:5000],
            "returncode": proc.returncode,
            "success": proc.returncode == 0
        })
    except asyncio.CancelledError:
        # 取消：杀掉进程
        try:
            proc.kill()
            await proc.wait()
        except (ProcessLookupError, UnboundLocalError):
            pass
        return json.dumps({
            "cancelled": True,
            "message": "命令已被用户取消。"
        })
    except Exception as e:
        return json.dumps({"error": str(e)})
