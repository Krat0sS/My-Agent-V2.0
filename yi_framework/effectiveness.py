# -*- coding: utf-8 -*-
"""
工具效果追踪器 — 让 Agent 越用越准

记录维度：task_tag × tool_name
存储：SQLite + WAL 模式（并发安全）
查询：双窗口加权（0.7×近N次 + 0.3×全量）
冷启动：task_tag 无数据 → 查 'general' → 返回默认分数
"""

import sqlite3
import time
import os
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class ToolScore:
    """工具在某任务类型下的效果评分"""
    tool_name: str
    success_count: int = 0
    fail_count: int = 0
    avg_duration_ms: float = 0
    success_rate: float = 0.5
    total_uses: int = 0


class ToolEffectiveness:
    """
    工具效果追踪器

    使用：
        eff = ToolEffectiveness()

        # 记录
        eff.record(task_tag="web-research", tool_name="web_search", success=True, duration_ms=1200)

        # 查询最佳工具（自动冷启动回退）
        best = eff.query_best("web-research", ["web_search", "ab_open"])
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'tool_effectiveness.db')
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表（WAL 模式）"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
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
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_tool
            ON tool_effectiveness(task_tag, tool_name)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON tool_effectiveness(timestamp)
        """)
        conn.commit()
        conn.close()

    def record(self, task_tag: str, tool_name: str, success: bool,
               duration_ms: float = 0, session_id: str = ""):
        """
        记录一次工具执行效果

        Args:
            task_tag: 任务标签（skill.name / template.name / "task:关键词" / "simple"）
            tool_name: 工具名
            success: 是否成功
            duration_ms: 执行耗时（毫秒）
            session_id: 会话ID
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO tool_effectiveness (task_tag, tool_name, success, duration_ms, timestamp, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_tag, tool_name, 1 if success else 0, duration_ms, time.time(), session_id)
        )
        conn.commit()
        conn.close()

    def query_best(self, task_tag: str, candidate_tools: List[str],
                   limit: int = 3) -> List[ToolScore]:
        """
        查询某任务类型下历史最佳工具。

        双窗口加权：0.7 × 最近10次 + 0.3 × 全量
        冷启动回退：task_tag 无数据 → 查 'general' → 返回默认分数

        Args:
            task_tag: 任务标签
            candidate_tools: 候选工具列表
            limit: 返回数量

        Returns:
            按效果排序的 ToolScore 列表
        """
        if not candidate_tools:
            return []

        # 第一次尝试：精确匹配 task_tag
        results = self._query_weighted(task_tag, candidate_tools, limit)

        # 冷启动回退：查 'general'
        if not results or all(s.total_uses == 0 for s in results):
            results = self._query_weighted("general", candidate_tools, limit)

        # 还是没数据：返回默认分数
        if not results or all(s.total_uses == 0 for s in results):
            return [ToolScore(tool_name=t, success_rate=0.5, total_uses=0)
                    for t in candidate_tools[:limit]]

        return results

    def _query_weighted(self, task_tag: str, candidate_tools: List[str],
                        limit: int, recent_n: int = 10,
                        short_weight: float = 0.7) -> List[ToolScore]:
        """双窗口加权查询"""
        results = []
        for tool in candidate_tools:
            overall = self._query_single(task_tag, tool)
            recent = self._query_single(task_tag, tool, limit=recent_n,
                                         order_by="timestamp DESC")

            if recent.total_uses == 0:
                score = overall.success_rate
            elif overall.total_uses == 0:
                score = 0.5
            else:
                score = (short_weight * recent.success_rate
                         + (1 - short_weight) * overall.success_rate)

            results.append(ToolScore(
                tool_name=tool,
                success_count=overall.success_count,
                fail_count=overall.fail_count,
                avg_duration_ms=overall.avg_duration_ms,
                success_rate=score,
                total_uses=overall.total_uses,
            ))

        results.sort(key=lambda x: (-x.success_rate, x.avg_duration_ms))
        return results[:limit]

    def _query_single(self, task_tag: str, tool_name: str,
                      limit: int = None,
                      order_by: str = "success_rate DESC, avg_duration ASC") -> ToolScore:
        """查询单个工具的效果统计"""
        conn = sqlite3.connect(self.db_path)

        if limit is not None:
            query = f"""
                SELECT
                    ? as tool_name,
                    SUM(success) as success_count,
                    COUNT(*) - SUM(success) as fail_count,
                    AVG(duration_ms) as avg_duration,
                    CAST(SUM(success) AS REAL) / COUNT(*) as success_rate,
                    COUNT(*) as total
                FROM (
                    SELECT success, duration_ms
                    FROM tool_effectiveness
                    WHERE task_tag = ? AND tool_name = ?
                    ORDER BY {order_by}
                    LIMIT ?
                )
            """
            params = [tool_name, task_tag, tool_name, limit]
        else:
            query = """
                SELECT
                    tool_name,
                    SUM(success) as success_count,
                    COUNT(*) - SUM(success) as fail_count,
                    AVG(duration_ms) as avg_duration,
                    CAST(SUM(success) AS REAL) / COUNT(*) as success_rate,
                    COUNT(*) as total
                FROM tool_effectiveness
                WHERE task_tag = ? AND tool_name = ?
                GROUP BY tool_name
            """
            params = [task_tag, tool_name]

        row = conn.execute(query, params).fetchone()
        conn.close()

        if not row or row[5] == 0:
            return ToolScore(tool_name=tool_name)

        return ToolScore(
            tool_name=row[0],
            success_count=row[1],
            fail_count=row[2],
            avg_duration_ms=row[3] or 0,
            success_rate=row[4] or 0,
            total_uses=row[5],
        )

    def get_tool_stats(self, tool_name: str) -> Dict[str, float]:
        """获取某工具在所有任务类型下的总体统计"""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("""
            SELECT COUNT(*), SUM(success), AVG(duration_ms)
            FROM tool_effectiveness WHERE tool_name = ?
        """, (tool_name,)).fetchone()
        conn.close()
        if not row or row[0] == 0:
            return {"total": 0, "success_rate": 0.5, "avg_duration_ms": 0}
        return {
            "total": row[0],
            "success_rate": row[1] / row[0] if row[0] > 0 else 0.5,
            "avg_duration_ms": row[2] or 0,
        }

    def get_recent_stats(self, limit: int = 100) -> Dict[str, dict]:
        """获取最近 limit 条记录中每个工具的聚合统计（用于 self_optimizer）"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("""
            SELECT tool_name, COUNT(*), SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END)
            FROM (
                SELECT tool_name, success
                FROM tool_effectiveness ORDER BY id DESC LIMIT ?
            ) GROUP BY tool_name
        """, (limit,)).fetchall()
        conn.close()
        return {
            tool: {"total": total, "fail_count": fail,
                   "fail_rate": fail / total if total > 0 else 0.0}
            for tool, total, fail in rows
        }

    def cleanup_old_records(self, days: int = 30):
        """清理超过N天的旧记录"""
        cutoff = time.time() - (days * 86400)
        conn = sqlite3.connect(self.db_path)
        deleted = conn.execute(
            "DELETE FROM tool_effectiveness WHERE timestamp < ?", (cutoff,)
        ).rowcount
        conn.commit()
        conn.close()
        return deleted


# 兼容旧接口名
GuaToolEffectiveness = ToolEffectiveness
