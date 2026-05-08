#!/usr/bin/env python3
"""
My-Agent v2.0 — 个人 AI Agent 框架

用法：
    python main.py                          # 交互式命令行
    python main.py --web                    # 启动 Web 服务
    python main.py --web --port 8080        # 指定端口
    python main.py "帮我写个排序算法"        # 单次提问
    python main.py --skills                 # 列出已加载的技能
    python main.py --stats                  # 查看执行统计

架构：
    - ToolRegistry：工具自动发现 + 动态 Schema
    - skill.md 驱动的技能系统：技能匹配优先于任务分解
    - 意图路由引擎：分类 → 匹配 → 执行/分解 → 沉淀
    - 执行日志数据库：所有操作打点，为进化提供数据
    - 安全模块：外部内容隔离 + Prompt Injection 防护

环境变量：
    LLM_API_KEY   — API Key（必填）
    LLM_BASE_URL  — API 地址
    LLM_MODEL     — 模型名
"""
import sys
import os
import json
import asyncio
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config


def _init():
    """初始化：加载工具注册表 + 技能系统"""
    from tools.registry import registry, discover_tools
    discover_tools()
    return registry


def _show_tool_log(console, tool_log: list[dict]):
    """展示工具调用日志"""
    if not tool_log:
        return
    from rich.table import Table
    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("🛠️ 工具", style="cyan")
    table.add_column("参数", max_width=40)
    table.add_column("耗时", justify="right")
    table.add_column("状态", justify="center")
    for entry in tool_log:
        status = "❌" if entry.get("error") else "✅"
        if entry.get("retries", 0) > 0:
            status += f" (重试{entry['retries']}次)"
        args_preview = ", ".join(f"{k}={v}" for k, v in entry.get("args", {}).items())
        elapsed = f"{entry.get('elapsed_ms', 0)}ms"
        table.add_row(entry["tool"], args_preview[:40], elapsed, status)
    console.print(table)


def _show_stats(console, stats: dict):
    """展示 Token 统计"""
    if not stats:
        return
    total = stats.get("total_tokens", 0)
    if total == 0:
        return
    prompt = stats.get("prompt_tokens", 0)
    completion = stats.get("completion_tokens", 0)
    tool_calls = stats.get("tool_calls_count", 0)
    rounds = stats.get("rounds", 0)
    cost = stats.get("estimated_cost_cny", 0)
    console.print(
        f"[dim]📊 Token: {total} (输入 {prompt} + 输出 {completion}) | "
        f"工具: {tool_calls} 次 | 轮次: {rounds} | "
        f"≈ ¥{cost}[/dim]"
    )


def _show_skills(console):
    """列出已加载的技能"""
    from skills.loader import load_all_skills
    skills = load_all_skills()
    if not skills:
        console.print("[yellow]暂无已加载的技能[/yellow]")
        console.print(f"[dim]技能目录: {os.path.join(config.WORKSPACE, 'skills')}[/dim]")
        return
    console.print(f"\n[bold]已加载技能 ({len(skills)}):[/bold]")
    for skill in skills:
        tools_str = ", ".join(skill.tools[:3]) if skill.tools else "无特殊要求"
        console.print(f"  🎯 [cyan]{skill.name}[/cyan] — {skill.goal[:60]}")
        console.print(f"     工具: {tools_str} | 步骤: {len(skill.steps)} 步")


def _show_exec_stats(console):
    """展示执行统计"""
    from data.execution_log import get_skill_stats, get_tool_error_stats, get_recent_tasks

    skill_stats = get_skill_stats()
    tool_errors = get_tool_error_stats()
    recent_tasks = get_recent_tasks(10)

    if skill_stats:
        console.print("\n[bold]🎯 技能使用统计:[/bold]")
        for s in skill_stats:
            success_rate = (s['successes'] / s['uses'] * 100) if s['uses'] > 0 else 0
            console.print(
                f"  {s['skill_name']}: {s['uses']} 次使用, "
                f"成功率 {success_rate:.0f}%, "
                f"平均耗时 {s['avg_duration']:.0f}ms"
            )

    if tool_errors:
        console.print("\n[bold]⚠️ 工具错误统计:[/bold]")
        for t in tool_errors:
            console.print(
                f"  {t['tool_name']}: {t['errors']}/{t['total']} 次错误 "
                f"({t['error_rate'] * 100:.0f}%)"
            )

    if recent_tasks:
        console.print(f"\n[bold]📋 最近 {len(recent_tasks)} 个任务:[/bold]")
        for t in recent_tasks[:5]:
            status = "✅" if t.get("success") else "❌"
            skill = t.get("matched_skill") or "(分解执行)"
            console.print(f"  {status} {t['user_input'][:40]} → {skill}")


async def cli_mode():
    """命令行交互模式"""
    from rich.console import Console
    from rich.panel import Panel
    from core.conversation import Conversation

    console = Console()

    registry = _init()

    console.print(Panel.fit(
        f"[bold cyan]{config.AGENT_NAME}[/bold cyan] [dim]v4.0[/dim]\n"
        "[dim]输入 q 退出 | /reset 重置 | /cancel 取消 | "
        "/tools 工具列表 | /skills 技能列表 | /stats 统计 | "
        "/log 调用日志 | /set key value 设置参数[/dim]",
        border_style="cyan"
    ))

    console.print(
        f"[dim]🔧 工具注册表: {registry.available_count()}/{registry.count()} 个可用[/dim]"
    )

    if not config.LLM_API_KEY:
        console.print("[red]❌ 错误: 未设置 LLM_API_KEY[/red]")
        console.print(f"[dim]API 地址: {config.LLM_BASE_URL}[/dim]")
        console.print(f"[dim]模型: {config.LLM_MODEL}[/dim]")
        console.print("[dim]请在 .env 文件中配置 LLM_API_KEY[/dim]")
        return

    conv = Conversation(session_id="cli-main")

    if conv.tool_log or len(conv.messages) > 1:
        console.print("[dim]已恢复上次会话[/dim]")

    loop = asyncio.get_running_loop()

    while True:
        try:
            user_input = await loop.run_in_executor(None, lambda: input("\n你: "))
        except (KeyboardInterrupt, EOFError):
            break

        if user_input.lower() in ("q", "quit", "exit"):
            break
        if user_input == "/reset":
            conv.reset()
            console.print("[dim]对话已重置[/dim]")
            continue
        if user_input == "/cancel":
            conv.cancel()
            console.print("[yellow]已发送取消信号[/yellow]")
            continue
        if user_input == "/tools":
            tool_list = registry.get_available_names()
            console.print(f"\n[bold]可用工具 ({len(tool_list)}):[/bold]")
            for t in tool_list:
                console.print(f"  • {t}")
            continue
        if user_input == "/skills":
            _show_skills(console)
            continue
        if user_input == "/stats":
            _show_exec_stats(console)
            continue
        if user_input == "/log":
            _show_tool_log(console, conv.get_tool_log())
            continue
        if user_input.startswith("/set "):
            parts = user_input.split(maxsplit=2)
            if len(parts) == 3:
                _, key, value = parts
                conv.memory.update_param(key, value)
                console.print(f"[green]已设置 {key} = {value}[/green]")
            else:
                console.print("[yellow]用法: /set <参数名> <值>[/yellow]")
            continue
        if not user_input.strip():
            continue

        with console.status("[bold cyan]思考中...[/bold cyan]"):
            def cli_confirm(cmd: str) -> bool:
                console.print(f"\n[bold yellow]⚠️ 该操作可能修改系统状态，是否确认执行？[/bold yellow]")
                console.print(f"[yellow]$ {cmd}[/yellow]")
                try:
                    from rich.prompt import Prompt
                    answer = Prompt.ask("[bold yellow]确认执行？[/bold yellow]", choices=["y", "n"], default="n")
                    return answer == "y"
                except (KeyboardInterrupt, EOFError):
                    return False

            def cli_progress(msg: str):
                console.print(f"  {msg}")

            try:
                result = await conv.send(
                    user_input,
                    on_confirm=cli_confirm,
                    on_progress=cli_progress,
                )
            except asyncio.CancelledError:
                console.print("[yellow]操作已取消[/yellow]")
                continue

        response = result.get("response", "")
        stats = result.get("stats", {})

        console.print(f"\n[bold cyan]{config.AGENT_NAME}[/bold cyan]: {response}")
        _show_stats(console, stats)

        if conv.tool_log:
            recent = conv.tool_log[-5:]
            if any(e.get("elapsed_ms", 0) > 1000 for e in recent):
                console.print("[dim]工具调用详情:[/dim]")
                _show_tool_log(console, recent)

    console.print("\n[dim]👋 再见[/dim]")
    await conv.cleanup()


def web_mode(port: int = None):
    """Web 服务模式 — 启动 Flask + HTML 前端"""
    import subprocess
    port = port or config.WEB_PORT
    print(f"\n🤖 {config.AGENT_NAME} Web 服务")
    print(f"   地址: http://localhost:{port}")
    print(f"   按 Ctrl+C 停止\n")
    subprocess.run([sys.executable, "server.py", "--port", str(port)])


async def single_query(query: str):
    """单次提问模式"""
    _init()
    from core.conversation import Conversation
    conv = Conversation(session_id="single", restore=False)
    try:
        result = await conv.send(query)
        print(result.get("response", ""))
    finally:
        await conv.cleanup()


def main():
    parser = argparse.ArgumentParser(description=f"{config.AGENT_NAME} v4.0 — AI 智能体")
    parser.add_argument("query", nargs="?", help="单次提问（直接传入问题）")
    parser.add_argument("--web", action="store_true", help="启动 Web 服务")
    parser.add_argument("--port", type=int, default=None, help="Web 服务端口（默认 8080）")
    parser.add_argument("--name", default=None, help="自定义智能体名称")
    parser.add_argument("--skills", action="store_true", help="列出已加载的技能")
    parser.add_argument("--stats", action="store_true", help="查看执行统计")

    args = parser.parse_args()

    if args.name:
        config.AGENT_NAME = args.name

    if args.skills:
        from rich.console import Console
        _init()
        _show_skills(Console())
    elif args.stats:
        from rich.console import Console
        _init()
        _show_exec_stats(Console())
    elif args.web:
        web_mode(args.port)
    elif args.query:
        asyncio.run(single_query(args.query))
    else:
        try:
            asyncio.run(cli_mode())
        except KeyboardInterrupt:
            print("\n👋 再见")


if __name__ == "__main__":
    main()
