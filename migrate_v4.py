#!/usr/bin/env python3
"""
V4 → V2.0 数据迁移脚本

迁移内容：
1. gua_effectiveness.db (hexagram × tool) → tool_effectiveness.db (task_tag × tool)
2. 旧格式 SKILL.md → 自动补充 YAML frontmatter
3. sessions/*.json → 保留（格式兼容）

用法：
    python migrate_v4.py [--dry-run]
"""
import os
import sys
import sqlite3
import shutil
import re
from pathlib import Path
from datetime import datetime


def find_workspace():
    """查找工作区目录"""
    ws = os.environ.get("WORKSPACE", os.path.expanduser("~/.my-agent/workspace"))
    if os.path.exists(ws):
        return ws
    # 尝试当前目录
    if os.path.exists("data"):
        return "."
    return None


def migrate_effectiveness(workspace: str, dry_run: bool = False):
    """迁移效果记录数据库"""
    old_db = os.path.join(workspace, "data", "gua_effectiveness.db")
    new_db = os.path.join(workspace, "data", "tool_effectiveness.db")

    if not os.path.exists(old_db):
        print("  ⏭️  未找到 gua_effectiveness.db，跳过")
        return 0

    if os.path.exists(new_db):
        print(f"  ⚠️  tool_effectiveness.db 已存在，将合并数据")

    if dry_run:
        conn = sqlite3.connect(old_db)
        count = conn.execute("SELECT COUNT(*) FROM gua_tool_effectiveness").fetchone()[0]
        conn.close()
        print(f"  📊 待迁移记录: {count} 条")
        return count

    # 读取旧数据
    old_conn = sqlite3.connect(old_db)
    rows = old_conn.execute(
        "SELECT hexagram, tool_name, success, duration_ms, timestamp, session_id "
        "FROM gua_tool_effectiveness"
    ).fetchall()
    old_conn.close()

    if not rows:
        print("  ⏭️  旧数据库为空，跳过")
        return 0

    # 写入新数据库
    os.makedirs(os.path.dirname(new_db), exist_ok=True)
    new_conn = sqlite3.connect(new_db)
    new_conn.execute("PRAGMA journal_mode=WAL")
    new_conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_effectiveness (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_tag TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            success INTEGER NOT NULL DEFAULT 0,
            duration_ms REAL DEFAULT 0,
            timestamp REAL NOT NULL,
            session_id TEXT DEFAULT ''
        )
    """)
    new_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_tool
        ON tool_effectiveness(task_tag, tool_name)
    """)

    migrated = 0
    for hexagram, tool_name, success, duration_ms, timestamp, session_id in rows:
        # hexagram → task_tag 映射：统一用 "general"（无法反推原始任务类型）
        task_tag = "general"
        new_conn.execute(
            "INSERT INTO tool_effectiveness (task_tag, tool_name, success, duration_ms, timestamp, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_tag, tool_name, success, duration_ms, timestamp, session_id or "")
        )
        migrated += 1

    new_conn.commit()
    new_conn.close()

    # 备份旧文件
    backup = old_db + f".bak.{datetime.now().strftime('%Y%m%d')}"
    shutil.copy2(old_db, backup)
    print(f"  ✅ 迁移完成: {migrated} 条记录")
    print(f"  📦 旧文件已备份: {backup}")
    return migrated


def migrate_skills(workspace: str, dry_run: bool = False):
    """迁移旧格式 SKILL.md（补充 YAML frontmatter）"""
    skills_dir = os.path.join(workspace, "skills")
    if not os.path.exists(skills_dir):
        print("  ⏭️  未找到 skills/ 目录，跳过")
        return 0

    migrated = 0
    for d in Path(skills_dir).iterdir():
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue

        content = skill_md.read_text(encoding="utf-8")

        # 已有 frontmatter → 跳过
        if re.match(r'^---\s*\n', content):
            continue

        # 提取旧格式信息
        sections = {}
        current_section = None
        current_lines = []
        for line in content.split("\n"):
            m = re.match(r'^##\s+(.+)', line)
            if m:
                if current_section:
                    sections[current_section] = "\n".join(current_lines).strip()
                current_section = m.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_section:
            sections[current_section] = "\n".join(current_lines).strip()

        goal = sections.get("目标", sections.get("Goal", ""))
        tools_text = sections.get("前置工具", sections.get("Required Tools", ""))
        tools = re.findall(r'`([a-z_][a-z0-9_]*)`', tools_text)

        # 生成 frontmatter
        frontmatter = f"""---
name: {d.name}
version: "1.0"
description: {goal[:100] if goal else d.name}
trigger:
  keywords: []
tools: {tools or []}
steps: []
---"""

        new_content = frontmatter + "\n" + content

        if dry_run:
            print(f"  📝 待迁移: {d.name}/SKILL.md")
        else:
            # 备份
            backup = str(skill_md) + ".bak"
            shutil.copy2(skill_md, backup)
            skill_md.write_text(new_content, encoding="utf-8")
            print(f"  ✅ 已迁移: {d.name}/SKILL.md")

        migrated += 1

    return migrated


def main():
    dry_run = "--dry-run" in sys.argv
    workspace = find_workspace()

    if not workspace:
        print("❌ 未找到工作区目录。请设置 WORKSPACE 环境变量或在项目根目录运行。")
        sys.exit(1)

    print(f"{'🔍 预览模式' if dry_run else '🚀 开始迁移'}")
    print(f"   工作区: {os.path.abspath(workspace)}")
    print()

    # 1. 效果记录迁移
    print("📊 迁移效果记录 (gua_effectiveness → tool_effectiveness)")
    eff_count = migrate_effectiveness(workspace, dry_run)
    print()

    # 2. 技能格式迁移
    print("🎯 迁移技能格式 (补充 YAML frontmatter)")
    skill_count = migrate_skills(workspace, dry_run)
    print()

    # 汇总
    print("=" * 40)
    if dry_run:
        print(f"预览完成: {eff_count} 条效果记录, {skill_count} 个技能待迁移")
        print("去掉 --dry-run 参数执行实际迁移")
    else:
        print(f"迁移完成: {eff_count} 条效果记录, {skill_count} 个技能")
        print("旧文件已备份（.bak 后缀），确认无误后可删除")


if __name__ == "__main__":
    main()
