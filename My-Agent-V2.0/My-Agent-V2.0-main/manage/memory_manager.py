"""
记忆管理器 — 记忆的查看、搜索、删除

封装 memory/memory_system.py，给 UI 层提供统一接口。
当前阶段只做查看+删除，手动添加等 Phase 4 向量检索完成后再加。
"""
import os
import json
from datetime import datetime


class MemoryManager:
    """记忆管理器"""

    def __init__(self, workspace_dir: str = None):
        if workspace_dir is None:
            import config
            workspace_dir = config.WORKSPACE
        self.workspace_dir = workspace_dir
        self.memory_dir = os.path.join(workspace_dir, "memory")
        self.memory_file = os.path.join(workspace_dir, "MEMORY.md")

    def _check_path_safe(self, path: str) -> dict:
        """调用 Phase 1 安全守卫检查路径"""
        try:
            from security.filesystem_guard import guard
            result = guard.check_path(path)
            if not result.safe:
                return {"safe": False, "reason": result.reason}
        except ImportError:
            pass
        return {"safe": True}

    def list_daily_memories(self) -> dict:
        """列出所有每日记忆文件（memory/YYYY-MM-DD.md）"""
        memories = []
        if not os.path.isdir(self.memory_dir):
            return {"success": True, "memories": []}

        for fname in sorted(os.listdir(self.memory_dir), reverse=True):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(self.memory_dir, fname)
            size = 0
            preview = ""
            try:
                size = os.path.getsize(fpath)
                with open(fpath, "r", encoding="utf-8") as f:
                    # 读前 200 字符作为预览
                    preview = f.read(200).strip()
            except Exception:
                pass

            memories.append({
                "name": fname,
                "date": fname.replace(".md", ""),
                "size": size,
                "preview": preview[:100],
                "path": fpath,
            })

        return {"success": True, "memories": memories, "count": len(memories)}

    def read_memory(self, filename: str) -> dict:
        """读取单个记忆文件的完整内容"""
        # 支持 "2026-05-05.md" 或 "MEMORY.md"
        if filename == "MEMORY.md":
            fpath = self.memory_file
        else:
            fpath = os.path.join(self.memory_dir, filename)

        check = self._check_path_safe(fpath)
        if not check["safe"]:
            return {"success": False, "error": check["reason"]}

        if not os.path.isfile(fpath):
            return {"success": False, "error": f"记忆文件不存在: {filename}"}

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            return {"success": True, "name": filename, "content": content, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_memories(self, keyword: str) -> dict:
        """在所有记忆文件中搜索关键词"""
        keyword_lower = keyword.lower()
        results = []

        # 搜索 MEMORY.md
        if os.path.isfile(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    content = f.read()
                if keyword_lower in content.lower():
                    # 找到匹配的行
                    matches = []
                    for i, line in enumerate(content.split("\n"), 1):
                        if keyword_lower in line.lower():
                            matches.append({"line": i, "text": line.strip()[:100]})
                    results.append({
                        "name": "MEMORY.md",
                        "matches": matches[:5],
                        "match_count": len(matches),
                    })
            except Exception:
                pass

        # 搜索 memory/*.md
        if os.path.isdir(self.memory_dir):
            for fname in sorted(os.listdir(self.memory_dir), reverse=True):
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(self.memory_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    if keyword_lower in content.lower():
                        matches = []
                        for i, line in enumerate(content.split("\n"), 1):
                            if keyword_lower in line.lower():
                                matches.append({"line": i, "text": line.strip()[:100]})
                        results.append({
                            "name": fname,
                            "matches": matches[:5],
                            "match_count": len(matches),
                        })
                except Exception:
                    pass

        return {"success": True, "keyword": keyword, "results": results, "file_count": len(results)}

    def delete_memory(self, filename: str, confirm: bool = False) -> dict:
        """删除记忆文件（移到 .trash/，需确认）"""
        if not confirm:
            return {
                "success": True,
                "needs_confirm": True,
                "message": f"确定删除记忆文件 {filename}？将移动到回收站。",
            }

        if filename == "MEMORY.md":
            return {"success": False, "error": "不能删除 MEMORY.md（长期记忆）"}

        fpath = os.path.join(self.memory_dir, filename)
        check = self._check_path_safe(fpath)
        if not check["safe"]:
            return {"success": False, "error": check["reason"]}

        if not os.path.isfile(fpath):
            return {"success": False, "error": f"记忆文件不存在: {filename}"}

        try:
            trash_dir = os.path.join(self.memory_dir, ".trash")
            os.makedirs(trash_dir, exist_ok=True)
            trash_dest = os.path.join(trash_dir, f"{filename}.{datetime.now().strftime('%Y%m%d%H%M%S')}")
            import shutil
            shutil.move(fpath, trash_dest)
            return {"success": True, "message": f"记忆 {filename} 已移动到回收站", "trash_path": trash_dest}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_stats(self) -> dict:
        """获取记忆统计"""
        daily_count = 0
        daily_total_size = 0
        if os.path.isdir(self.memory_dir):
            for fname in os.listdir(self.memory_dir):
                if fname.endswith(".md"):
                    daily_count += 1
                    daily_total_size += os.path.getsize(os.path.join(self.memory_dir, fname))

        memory_md_size = 0
        if os.path.isfile(self.memory_file):
            memory_md_size = os.path.getsize(self.memory_file)

        return {
            "success": True,
            "daily_count": daily_count,
            "daily_total_size": daily_total_size,
            "memory_md_size": memory_md_size,
            "total_size": daily_total_size + memory_md_size,
        }
