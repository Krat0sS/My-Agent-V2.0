# -*- coding: utf-8 -*-
"""
Phase 5 验收测试：经验回流 + 技能 staging

测试 1: 效果表有数据时，候选工具按 success_rate 排序
测试 2: 新 skill.md 写入 .staging/ 而非 skills/
测试 3: --approve-skills 命令将 staging 文件移动到 skills/
测试 4: 7 天前的 staging 文件被归档
测试 5: staging 超过 20 个时，最旧的被删除
"""
import sys
import os
import time
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yi_framework.effectiveness import GuaToolEffectiveness
from skills.staging import SkillStaging


# ═══ 测试 1: 候选工具按 success_rate 排序 ═══

def test_query_best_tools_sorted():
    db = os.path.join(tempfile.mkdtemp(), 'test.db')
    eff = GuaToolEffectiveness(db)

    # tool_a: 80%, tool_b: 40%, tool_c: 无数据
    for i in range(10):
        eff.record('test-task', 'tool_a', success=(i < 8), duration_ms=100)
        eff.record('test-task', 'tool_b', success=(i < 4), duration_ms=200)

    results = eff.query_best('test-task', ['tool_a', 'tool_b', 'tool_c'])

    assert results[0].tool_name == 'tool_a', f"Expected tool_a first, got {results[0].tool_name}"
    # tool_c 无数据=0.5 > tool_b=0.4, 所以 tool_c 排第二
    assert results[1].tool_name == 'tool_c', f"Expected tool_c second (0.5>0.4), got {results[1].tool_name}"
    assert results[2].tool_name == 'tool_b', f"Expected tool_b third, got {results[2].tool_name}"
    assert results[1].success_rate == 0.5, f"Expected tool_c rate=0.5 (no data), got {results[1].success_rate}"

    shutil.rmtree(os.path.dirname(db))
    print("✅ 测试 1 通过: 候选工具按 success_rate 排序，无数据=0.5")


# ═══ 测试 2: 双窗口加权 — 近期失败检测 ═══

def test_dual_window_detects_decline():
    db = os.path.join(tempfile.mkdtemp(), 'test.db')
    eff = GuaToolEffectiveness(db)

    # tool_a: 过去很好(100次90成功)，最近10次全失败
    for i in range(100):
        eff.record('test-decline', 'tool_a', success=(i < 90), duration_ms=100)

    # tool_b: 一般(50次35成功)，最近10次全成功
    for i in range(50):
        success = (i < 25) or (i >= 40)  # 前25成功，中间15失败，后10成功
        eff.record('test-decline', 'tool_b', success=success, duration_ms=150)

    # query_best 使用双窗口加权
    results = eff.query_best('test-decline', ['tool_a', 'tool_b'])
    # tool_a: recent=0/10=0.0, overall=90/100=0.9, weighted=0.7*0+0.3*0.9=0.27
    # tool_b: recent=10/10=1.0, overall=35/50=0.7, weighted=0.7*1.0+0.3*0.7=0.91
    assert results[0].tool_name == 'tool_b', f"Expected tool_b first (tool_a declining), got {results[0].tool_name}"

    shutil.rmtree(os.path.dirname(db))
    print("✅ 测试 2 通过: 双窗口加权正确检测工具衰退")


# ═══ 测试 3: staging 写入 .staging/ 而非 skills/ ═══

def test_stage_writes_to_staging():
    base = tempfile.mkdtemp()
    s = SkillStaging(base)

    path = s.stage('my_skill', '# My Skill\nContent here')

    assert os.path.exists(path), f"Staging file should exist: {path}"
    assert '.staging' in path, f"Should be in .staging/: {path}"
    assert 'my_skill.md' in path, f"Should be named my_skill.md: {path}"

    # skills/ 目录下不应有这个文件
    skills_path = os.path.join(base, 'skills', 'my_skill.md')
    assert not os.path.exists(skills_path), f"Should NOT be in skills/ yet: {skills_path}"

    shutil.rmtree(base)
    print("✅ 测试 3 通过: staging 写入 .staging/ 而非 skills/")


# ═══ 测试 4: approve 将 staging 移动到 skills/ ═══

def test_approve_moves_to_skills():
    base = tempfile.mkdtemp()
    s = SkillStaging(base)

    s.stage('approved_skill', '# Approved\nContent')
    assert len(s.list_pending()) == 1

    result = s.approve('approved_skill')
    assert result is not None, "approve should return path"
    assert os.path.exists(result), f"Approved file should exist: {result}"
    assert 'skills/' in result and '.staging' not in result, f"Should be in skills/: {result}"
    assert len(s.list_pending()) == 0, "Should have no pending after approve"

    shutil.rmtree(base)
    print("✅ 测试 4 通过: approve 将 staging 移动到 skills/")


# ═══ 测试 5: TTL 归档 ═══

def test_ttl_archive():
    base = tempfile.mkdtemp()
    s = SkillStaging(base)

    # 先暂存两个文件
    s.stage('old_skill', '# Old Skill')
    s.stage('new_skill', '# New Skill')

    assert len(s.list_pending()) == 2

    # 手动修改 old_skill 的时间为 8 天前
    old_path = os.path.join(s.staging_path, 'old_skill.md')
    old_time = time.time() - (8 * 86400)
    os.utime(old_path, (old_time, old_time))

    # 清理 TTL
    archived = s.cleanup_ttl()

    assert len(archived) == 1, f"Expected 1 archived, got {len(archived)}"
    assert 'old_skill.md' in archived[0]
    assert len(s.list_pending()) == 1, f"Expected 1 pending, got {len(s.list_pending())}"

    # 归档文件应存在
    archive_path = os.path.join(s.archive_path, 'old_skill.md')
    assert os.path.exists(archive_path), f"Archived file should exist: {archive_path}"

    shutil.rmtree(base)
    print("✅ 测试 5 通过: 7 天前的 staging 文件被归档")


# ═══ 测试 6: 文件上限 ═══

def test_max_files_limit():
    base = tempfile.mkdtemp()
    s = SkillStaging(base)
    s.MAX_FILES = 5  # 降低上限便于测试

    # 暂存 5 个技能（间隔一小段时间确保时间戳不同）
    for i in range(5):
        s.stage(f'skill_{i}', f'# Skill {i}')
        time.sleep(0.01)

    assert len(s.list_pending()) == 5

    # 记录当前 pending 名称
    before = [p['name'] for p in s.list_pending()]

    # 再暂存 1 个 → 应该触发归档最旧的
    s.stage('skill_5', '# Skill 5')

    pending = s.list_pending()
    assert len(pending) == 5, f"Expected 5 pending (limit), got {len(pending)}"

    # 最旧的（第一个暂存的）应该被归档
    names = [p['name'] for p in pending]
    assert 'skill_5' in names, f"skill_5 should be pending, but pending={names}"

    # 确认确实有一个被归档了
    archived_files = os.listdir(s.archive_path)
    assert len(archived_files) == 1, f"Expected 1 archived, got {len(archived_files)}: {archived_files}"

    shutil.rmtree(base)
    print("✅ 测试 6 通过: staging 超过上限时，最旧的被归档")


if __name__ == "__main__":
    test_query_best_tools_sorted()
    test_dual_window_detects_decline()
    test_stage_writes_to_staging()
    test_approve_moves_to_skills()
    test_ttl_archive()
    test_max_files_limit()
    print("\n🎉 Phase 5 全部 6 个验收测试通过！")
