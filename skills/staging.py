# -*- coding: utf-8 -*-
"""
技能 staging 机制 — skill.md 先暂存，人工确认后生效

设计原则：
- 生成的 skill.md 先写入 skills/.staging/ 目录
- 用户通过 CLI 命令 --approve-skills 批量移动到 skills/
- staging 文件增加 TTL：超过 7 天未采纳的自动归档
- staging 目录文件上限 20 个，超出时删除最旧的
"""

import os
import time
import shutil
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("skill_staging")


class SkillStaging:
    """技能暂存管理器"""

    STAGING_DIR = "skills/.staging"
    ARCHIVE_DIR = "skills/.staging/archived"
    MAX_FILES = 20
    TTL_DAYS = 7

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.base_dir = base_dir
        self.staging_path = os.path.join(base_dir, self.STAGING_DIR)
        self.archive_path = os.path.join(base_dir, self.ARCHIVE_DIR)
        os.makedirs(self.staging_path, exist_ok=True)
        os.makedirs(self.archive_path, exist_ok=True)

    def stage(self, name: str, content: str, skip_dedup: bool = False) -> Optional[str]:
        """暂存一个技能文件

        Args:
            name: 技能名（不含 .md 后缀）
            content: skill.md 内容
            skip_dedup: 跳过去重检查（用于手动导入）

        Returns:
            staging 文件路径，或 None（如果被去重跳过）
        """
        # 清理过期文件
        self.cleanup_ttl()

        # 检查上限
        self._enforce_limit()

        # 语义去重：检查是否与已有技能太相似
        if not skip_dedup and self._is_duplicate(name, content):
            logger.info(f"[staging] 跳过暂存: {name}（与已有技能重复）")
            return None

        filename = f"{name}.md" if not name.endswith(".md") else name
        filepath = os.path.join(self.staging_path, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"[staging] 暂存技能: {filename}")
        return filepath

    def _is_duplicate(self, new_name: str, new_content: str,
                      threshold: float = 0.85) -> bool:
        """检查新技能是否与已有技能太相似

        策略：先用字符重叠度快速筛选，再用 BM25 精确判断

        Args:
            new_name: 新技能名
            new_content: 新技能内容
            threshold: 相似度阈值（0-1）

        Returns:
            True 表示重复，应跳过
        """
        # 收集已有技能（staging + 正式）
        existing = []

        # staging 中的技能
        for f in self._list_staging_files():
            if f.stem != new_name:
                try:
                    content = f.read_text(encoding="utf-8")
                    existing.append((f.stem, content))
                except Exception:
                    pass

        # 正式技能
        try:
            from skills.loader import load_all_skills
            for skill in load_all_skills():
                if skill.name != new_name:
                    existing.append((skill.name, skill.raw_md))
        except ImportError:
            pass

        if not existing:
            return False

        # 快速筛选：字符级 n-gram 重叠度
        new_doc = self._extract_skill_doc(new_name, new_content)
        new_ngrams = set(self._ngrams(new_doc.lower(), 3))

        for name, content in existing:
            doc = self._extract_skill_doc(name, content)
            doc_ngrams = set(self._ngrams(doc.lower(), 3))

            if not new_ngrams or not doc_ngrams:
                continue

            overlap = len(new_ngrams & doc_ngrams) / max(len(new_ngrams), len(doc_ngrams))
            if overlap >= threshold:
                logger.info(f"[staging 去重] '{new_name}' 与 '{name}' 字符重叠 {overlap:.2f} >= {threshold}")
                return True

        # BM25 精确判断（文档多时更准确）
        try:
            from core.bm25 import BM25Index
            index = BM25Index()
            for name, content in existing:
                doc = self._extract_skill_doc(name, content)
                index.add(name, doc)
            index.build()

            results = index.search(new_doc, top_k=1)
            if results:
                best_name, best_score = results[0]
                # BM25 分数归一化
                normalized = min(1.0, best_score / 6.0)
                if normalized >= threshold:
                    logger.info(f"[staging 去重] '{new_name}' 与 '{best_name}' BM25 {normalized:.2f} >= {threshold}")
                    return True
        except ImportError:
            pass

        return False

    @staticmethod
    def _ngrams(s: str, n: int) -> list:
        return [s[i:i+n] for i in range(len(s)-n+1)]

    @staticmethod
    def _extract_skill_doc(name: str, content: str) -> str:
        """从 SKILL.md 提取用于去重的文档文本"""
        import re
        # 提取目标/Goal 段落
        goal = ""
        m = re.search(r'(?:##\s*(?:目标|Goal))\s*\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if m:
            goal = m.group(1).strip()[:200]

        # 提取步骤关键词
        steps = ""
        m = re.search(r'(?:##\s*(?:执行步骤|Steps))\s*\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if m:
            steps = m.group(1).strip()[:300]

        return f"{name} {goal} {steps}"

    def approve(self, name: str) -> Optional[str]:
        """批准单个技能，从 staging 移动到 skills/

        Args:
            name: 技能名（不含 .md 后缀）

        Returns:
            最终路径，或 None（如果文件不存在）
        """
        filename = f"{name}.md" if not name.endswith(".md") else name
        src = os.path.join(self.staging_path, filename)
        if not os.path.exists(src):
            return None

        dst_dir = os.path.join(self.base_dir, "skills")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, filename)

        shutil.move(src, dst)
        logger.info(f"[staging] 批准技能: {filename} → skills/")
        return dst

    def approve_all(self) -> List[str]:
        """批准所有暂存的技能

        Returns:
            已批准的技能文件名列表
        """
        approved = []
        for f in self._list_staging_files():
            name = f.stem
            result = self.approve(name)
            if result:
                approved.append(f.name)
        return approved

    def cleanup_ttl(self) -> List[str]:
        """清理超时 staging 文件，归档到 archived/

        Returns:
            已归档的文件名列表
        """
        archived = []
        for f in self._list_staging_files():
            age_days = (time.time() - f.stat().st_mtime) / 86400
            if age_days > self.TTL_DAYS:
                dest = os.path.join(self.archive_path, f.name)
                shutil.move(str(f), dest)
                logger.info(f"[staging TTL] 归档: {f.name} (已 {age_days:.1f} 天) → {dest}")
                archived.append(f.name)
        return archived

    def list_pending(self) -> List[dict]:
        """列出所有暂存中的技能

        Returns:
            [{name, path, age_days, size}, ...]
        """
        result = []
        for f in self._list_staging_files():
            age_days = (time.time() - f.stat().st_mtime) / 86400
            result.append({
                "name": f.stem,
                "path": str(f),
                "age_days": round(age_days, 1),
                "size": f.stat().st_size,
            })
        return result

    def _list_staging_files(self) -> List[Path]:
        """列出 staging 目录中的 .md 文件（按修改时间排序）"""
        files = [
            Path(os.path.join(self.staging_path, f))
            for f in os.listdir(self.staging_path)
            if f.endswith(".md") and os.path.isfile(os.path.join(self.staging_path, f))
        ]
        files.sort(key=lambda x: x.stat().st_mtime)
        return files

    def _enforce_limit(self):
        """强制执行文件上限 — 超出时删除最旧的"""
        files = self._list_staging_files()
        while len(files) >= self.MAX_FILES:
            oldest = files.pop(0)
            # 归档而不是直接删除
            dest = os.path.join(self.archive_path, oldest.name)
            shutil.move(str(oldest), dest)
            logger.info(f"[staging 上限] 归档最旧文件: {oldest.name} → {dest}")
