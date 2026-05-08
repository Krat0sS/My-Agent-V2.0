"""
技能管理器 — skill.md 文件的增删改查

扫描 skills/ 子目录中的 SKILL.md 文件，给 UI 层提供统一接口。
"""
import os
import shutil
from datetime import datetime
from pathlib import Path


class SkillManager:
    """技能管理器"""

    def __init__(self, skills_dir: str = None):
        if skills_dir is None:
            skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
        self.skills_dir = os.path.abspath(skills_dir)
        self.trash_dir = os.path.join(self.skills_dir, ".trash")
        os.makedirs(self.trash_dir, exist_ok=True)

    def _skill_path(self, skill_name: str) -> str:
        """获取技能 SKILL.md 的完整路径"""
        # 支持 "file-search" 或 "file-search/SKILL.md" 两种格式
        if skill_name.endswith("/SKILL.md") or skill_name.endswith("\\SKILL.md"):
            return os.path.join(self.skills_dir, skill_name)
        return os.path.join(self.skills_dir, skill_name, "SKILL.md")

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

    def list_skills(self) -> dict:
        """列出所有技能（扫描子目录中的 SKILL.md）"""
        skills = []
        if not os.path.isdir(self.skills_dir):
            return {"success": True, "skills": []}

        for entry in sorted(os.listdir(self.skills_dir)):
            entry_path = os.path.join(self.skills_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry.startswith(".") or entry.startswith("__"):
                continue
            skill_md = os.path.join(entry_path, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue

            # 读第一行作为预览
            preview = ""
            size = 0
            modified = 0
            try:
                size = os.path.getsize(skill_md)
                modified = os.path.getmtime(skill_md)
                with open(skill_md, "r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    preview = first_line.lstrip("# ").strip()[:80]
            except Exception:
                pass

            skills.append({
                "name": entry,
                "preview": preview,
                "size": size,
                "modified": modified,
                "path": skill_md,
            })

        return {"success": True, "skills": skills, "count": len(skills)}

    def read_skill(self, skill_name: str) -> dict:
        """读取技能完整内容"""
        fpath = self._skill_path(skill_name)

        # 安全检查
        check = self._check_path_safe(fpath)
        if not check["safe"]:
            return {"success": False, "error": check["reason"]}

        if not os.path.isfile(fpath):
            return {"success": False, "error": f"技能不存在: {skill_name}"}

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            return {"success": True, "name": skill_name, "content": content, "path": fpath}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_skill(self, name: str, description: str = "") -> dict:
        """创建新技能（生成标准 SKILL.md 模板）"""
        skill_dir = os.path.join(self.skills_dir, name)

        if os.path.exists(skill_dir):
            return {"success": False, "error": f"技能已存在: {name}"}

        # 安全检查
        check = self._check_path_safe(skill_dir)
        if not check["safe"]:
            return {"success": False, "error": check["reason"]}

        try:
            os.makedirs(skill_dir, exist_ok=True)
            template = f"""# {name}

> {description or '在此填写技能描述'}

## 使用场景

描述何时使用此技能。

## 工具

列出此技能需要的工具。

## 示例

提供使用示例。
"""
            skill_md = os.path.join(skill_dir, "SKILL.md")
            with open(skill_md, "w", encoding="utf-8") as f:
                f.write(template)
            return {"success": True, "name": name, "path": skill_md}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_skill(self, skill_name: str, content: str) -> dict:
        """更新技能内容（先备份）"""
        fpath = self._skill_path(skill_name)

        # 安全检查
        check = self._check_path_safe(fpath)
        if not check["safe"]:
            return {"success": False, "error": check["reason"]}

        if not os.path.isfile(fpath):
            return {"success": False, "error": f"技能不存在: {skill_name}"}

        try:
            # 备份到 .trash/
            backup_name = f"{skill_name}.{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
            backup_path = os.path.join(self.trash_dir, backup_name)
            shutil.copy2(fpath, backup_path)

            # 写入新内容
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "name": skill_name, "backup": backup_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_skill(self, skill_name: str, confirm: bool = False) -> dict:
        """删除技能（移到 .trash/，需确认）"""
        if not confirm:
            return {
                "success": True,
                "needs_confirm": True,
                "message": f"确定删除技能 {skill_name}？将移动到回收站。",
            }

        skill_dir = os.path.join(self.skills_dir, skill_name)
        if not os.path.isdir(skill_dir):
            return {"success": False, "error": f"技能不存在: {skill_name}"}

        # 安全检查
        check = self._check_path_safe(skill_dir)
        if not check["safe"]:
            return {"success": False, "error": check["reason"]}

        try:
            trash_dest = os.path.join(self.trash_dir, f"{skill_name}.{datetime.now().strftime('%Y%m%d%H%M%S')}")
            shutil.move(skill_dir, trash_dest)
            return {"success": True, "message": f"技能 {skill_name} 已移动到回收站", "trash_path": trash_dest}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def validate_skill(self, skill_name: str) -> dict:
        """检查技能 SKILL.md 格式是否规范"""
        result = self.read_skill(skill_name)
        if not result["success"]:
            return result

        content = result["content"]
        errors = []
        warnings = []

        # 基本格式检查
        if not content.strip().startswith("#"):
            errors.append("SKILL.md 应以 # 标题开头")

        if "##" not in content:
            warnings.append("建议使用 ## 分节（使用场景、工具、示例等）")

        if len(content.strip()) < 50:
            warnings.append("内容过短，建议补充使用场景和示例")

        return {
            "success": True,
            "name": skill_name,
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }
