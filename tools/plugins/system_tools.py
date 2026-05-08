"""
系统工具插件 — run_command / run_command_confirmed
从 builtin.py 拆分，自注册到 ToolRegistry
"""
import json
from tools.registry import registry
from tools.tool_utils import ToolResult


def _run_command(command: str, cwd: str = None, timeout: int = 30) -> str:
    """同步包装器 — 由 conversation.py 通过 run_in_executor 调用"""
    from tools.subprocess_runner import run_command_async
    import asyncio
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, run_command_async(command, cwd, timeout))
            result = future.result(timeout=timeout + 5)
    except RuntimeError:
        result = asyncio.run(run_command_async(command, cwd, timeout))
    except Exception as e:
        return ToolResult.fail(f"命令执行异常: {e}", "E_COMMAND_FAILED",
                               recoverable=True, hint="检查命令语法和工作目录。")
    # subprocess_runner 已返回 JSON 字符串，兼容旧格式透传
    return result


def _run_command_confirmed(command: str, cwd: str = None, timeout: int = 30) -> str:
    """同步包装器"""
    from tools.subprocess_runner import run_command_confirmed_async
    import asyncio
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, run_command_confirmed_async(command, cwd, timeout))
            result = future.result(timeout=timeout + 5)
    except RuntimeError:
        result = asyncio.run(run_command_confirmed_async(command, cwd, timeout))
    except Exception as e:
        return ToolResult.fail(f"命令执行异常: {e}", "E_COMMAND_FAILED",
                               recoverable=True, hint="检查命令语法和工作目录。")
    return result


registry.register(
    name="run_command",
    description="执行 shell 命令。对于危险命令（rm, chmod, pip install, git push 等）会要求用户确认。支持超时和取消。",
    schema={
        "name": "run_command",
        "description": "执行 shell 命令。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"},
                "cwd": {"type": "string", "description": "工作目录", "default": None},
                "timeout": {"type": "integer", "description": "超时秒数", "default": 30}
            },
            "required": ["command"]
        }
    },
    handler=_run_command,
    category="system",
    risk_level="high",
)


registry.register(
    name="run_command_confirmed",
    description="执行已确认的危险命令（跳过确认检查）。仅在用户明确同意后使用。支持超时和取消。",
    schema={
        "name": "run_command_confirmed",
        "description": "执行已确认的危险命令。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令（已确认）"},
                "cwd": {"type": "string", "description": "工作目录", "default": None},
                "timeout": {"type": "integer", "description": "超时秒数", "default": 30}
            },
            "required": ["command"]
        }
    },
    handler=_run_command_confirmed,
    category="system",
    risk_level="high",
)
