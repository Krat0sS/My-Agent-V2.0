# CHANGELOG v4.0

> 基于 V3 代码库审查 + 三轮专家评审的综合改造

## Phase 1: Profile 合规校验 ✅

**核心改动**: ExecutionProfile 从"建议"升级为"硬约束"

- `workflow.py`: `WorkflowRunner.__init__` 新增 `profile` 参数
- `workflow.py`: 新增 `_profile_compliance_check()` 方法
  - `parallel=False` → `max_parallel=1` 强制串行
  - `risk_tolerance<0.3` → high risk 步骤降级或拦截
  - `max_retries` 覆盖步骤默认 retry
  - `timeout_seconds` 覆盖步骤默认 timeout
- `conversation.py`: 两处 WorkflowRunner 传入 `profile=self._current_profile`

## Phase 2: YiRuntime 反馈环闭合 ✅

**核心改动**: 防震荡 + 连续失败/成功快速通道

- `runtime.py`: 新增 `_check_force_flip()` 快速通道
  - 连续 3 次失败 → 全爻动翻转（保守模式）
  - 连续 5 次成功 → 全爻动翻转（激进模式）
  - 快速通道绕过时间间隔检查
- `runtime.py`: `_should_trigger_change()` 增加频率限制
  - 30 次操作内翻转不超过 5 次
- `runtime.py`: 新增 `_change_count_30ops` 防震荡计数器

## Phase 3: dayan.py 瘦身 + LLM prompt 清洗 ✅

**核心改动**: 消除控制面的 LLM 依赖，让约束对 LLM 透明

- `profiles.py`: 新增 `is_crisis()` 函数
  - `risk_tolerance < 0.15` 且 `rollback == "full"` → 危机
  - 替代 dayan.py 的 action_hint 危机检测
- `conversation.py`: 危机检测改用 `is_crisis(self._current_profile)`
- `conversation.py`: 新增 `_get_profile_constraint_prompt()`
  - 串行/低风险/不重试/完全回滚 → 约束文本
  - 不含任何易经术语（LLM 不知道约束来源）
- `conversation.py`: 新增 `_inject_profile_constraints()`
  - 每轮 LLM 对话前注入/替换约束消息

## Phase 4: 平台可达性扩展 d1 ✅

**核心改动**: YiRuntime 三维向量支持多设备感知

- `yi_framework/platform.py`: 新增 PlatformReachability 模块
  - `windows`/`linux_ssh`/`android_adb` 状态
  - `score()`: 连接数/最大平台数(3)
  - `is_platform_available()`: 按平台名查询
- `runtime.py`: d1 维度正交化
  - d1 从工具耗时+平台可达性推导（不与 d2 共享信号）
  - 新增 `_update_d1_resource()` 方法
  - `tick()` 接受可选 `platform` 参数
- `registry.py`: 工具平台字段 + 过滤
  - `ToolDefinition` 新增 `platform` 字段
  - `set_platform_filter()` 方法

## Phase 5: 经验回流 + 技能 staging ✅

**核心改动**: 让系统"越用越强"，但不碰代码级自修改

- `effectiveness.py`: 双窗口加权查询
  - `query_best_tools_v2()`: `0.7*最近N次 + 0.3*全量`
  - 正确检测工具衰退
- `skills/staging.py`: 技能暂存机制
  - `stage()`: 写入 `skills/.staging/` 而非 `skills/`
  - `approve()`: 批准后移动到 `skills/`
  - `cleanup_ttl()`: 7 天未采纳自动归档
  - `_enforce_limit()`: 上限 20 个，超出归档最旧的
- `conversation.py`: 技能沉淀改走 staging

## Phase 6: 清理 + 文档 ✅

- 删除 `tools/builtin_compat.py`（8 个文件 import 已更新）
- 清理过时注释（太极诊断常量、万物生成器、五行编排器）
- 更新 README.md 反映 V4 架构
- 更新 `registry.py` 移除 `builtin_compat.py` 跳过逻辑

## 测试结果

```
Phase 1: 6/6 通过
Phase 2: 6/6 通过
Phase 3: 6/6 通过
Phase 4: 6/6 通过
Phase 5: 6/6 通过
已有测试: 13/13 通过（无回归）
总计: 43/43
```

## 不做的事（明确排除）

| 排除项 | 原因 |
|--------|------|
| 代码级自我升级 | 安全风险过高 |
| AST 审计器 | LLM 可以绕过 |
| iOS 操控 | 沙箱不允许 |
| 时辰感知 (temporal.py) | 无因果关系 |
| 万物生成器 (wanwu.py) | 已在 V3 确认无用 |
| 五行编排器 (orchestrator.py) | 已被 profiles.py 覆盖 |
| 变爻恢复引擎 (change_engine.py) | 已被 Profile 重试逻辑覆盖 |
