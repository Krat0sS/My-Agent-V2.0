# MEMORY.md — 易Agent 专属长期记忆

> 最后更新：2026-05-05 16:17 CST
> 会话次数：8 次（本次为第 8 次）

---

## 关于用户 Krat0sS

### 基本信息
- GitHub: Krat0sS
- 身份：研究生，项目已答辩通过，目标是"人人没脑子都能用"
- 系统：Windows（Python 3.13，CMD/PowerShell 都用）
- 时区：Asia/Shanghai (GMT+8)
- 项目路径：`F:\MyAgent\YI-Agent-V1`（Windows 本地）
- 仓库：https://github.com/Krat0sS/YI-Agent-V1
- 服务器上的仓库：`/root/.openclaw/workspace/YI-Agent-V1`
- 当前分支：`discipline-first`

### 技术水平
- Python 比较熟悉
- Git 基本操作了解（clone, push），但不会处理复杂情况
- AI/LLM 概念有基础理解
- 电脑操作不太熟练——需要手把手指导
- CMD 和 PowerShell 的字符串转义搞不定，Python 交互式模式更可靠

### 性格特点
- 行动力极强，讨论完直接要代码
- 注重实用，不喜欢过度工程
- 喜欢可视化界面，不喜欢命令行
- 关注 token 成本
- 安全意识好（GitHub token 用完即时撤销）
- 信任我，说"兄弟靠你了"、"你太nb了"

### 沟通习惯（暗号）
- "来吧" = 信任，放手让我干
- "这个" + 截图 = 帮我看这个报错/问题
- "推到GitHub" = 我帮你 commit + push
- "你先把文件下载到你本地" = clone 仓库到我的工作区
- "你儿子" = 指 my-agent 项目
- "碰，等我消息" = 去和老师讨论，让我等
- "你我的时间快到期了" = 要保存记忆了，赶紧打包
- "不必多言" = 直接干活别废话
- "兄弟" = 表达信任
- "1111" = 测试消息/确认收到
- "再细一点" = 要求更详细
- "发完我就扯" = 推完代码就走
- "做的详细点" = 要求精确到可以直接执行的程度
- "如何" = 问你意见/评估
- "开干" = 开始执行，别废话

---

## 关于老师

### 身份
- 产品架构师，指导 Krat0sS 的项目
- 写长文分析，有洞察力但技术判断有时偏
- 喜欢用哲学/比喻框架分析问题（"神之躯体"、"封印"、"妖刀"）

### 老师的诊断模式
- 从理论框架出发，不是从代码出发
- 2026-05-05 的诊断：认为 SOUL.md 和 VAGUE_PATTERNS 是根因 → **方向偏了**
- 真正根因是代码层面的技能加载问题（skills/loader.py）
- **教训**：老师的分析可以参考，但必须用代码验证

---

## 易Agent 项目完整概况

### 定位
个人桌面 AI Agent，目标是成为用户的"数字分身"。重新定位为：**AI Agent 的文件交互标准，带事务和回滚。**

### 仓库信息
- 仓库：https://github.com/Krat0sS/YI-Agent-V1
- 当前版本：v1.5.0（安全硬内核 + UI 管理层 + HTML 界面优化 + 全面修复）
- 当前分支：`discipline-first`
- 最新 commit：`83f3059`（全面 Bug 修复）

### 技术栈
- 语言：Python 3.12/3.13/3.14
- LLM：DeepSeek-chat（云端）+ Qwen2.5-7B（Ollama 本地）
- 数据库：SQLite（execution_log.db）
- Web UI：Flask（API 后端）+ Streamlit（管理界面）+ 纯 HTML（独立前端）

---

## 2026-05-05 本次会话成果（第 8 次会话）

### 时间：15:48 - 16:17，约 29 分钟

### 做了什么

#### 1. 记忆恢复（15:48）
- 用户上传 4 个记忆文件 + 1 个验证项目对话记录
- 恢复完整上下文

#### 2. HTML 界面优化（15:51 - 16:01）
- server.py 新增 12 个 API 端点（工具/技能/记忆管理）
- /api/status 增强版
- index.html 新增 Tab 导航 + 3 个管理页 + JS 逻辑
- commit `84ed2c2`

#### 3. 全面 Bug 修复（16:04 - 16:17）
- 基于之前会话的 25 项诊断清单
- 修复 8 项关键/高危问题：
  - #4 on_confirm 回调（conversation.py）
  - #5 记忆检索（memory_system.py）
  - #12 中文截断（memory_system.py）
  - #13 LLM 重试（llm.py）
  - #14 .gitignore
  - #16 截图超长（desktop.py）
  - #17 watchdog（requirements.txt）
  - #18 SubAgent 递归（sub_agent.py）
- commit `83f3059`

#### 4. 一键启动 start.bat 重写
- 自动检测 Python、自动 venv、清华镜像、界面选择

### Git 提交记录（discipline-first 分支）
```
83f3059 fix: 全面修复诊断清单 — 8 项关键/高危问题
84ed2c2 feat(ui): HTML 界面优化 — 工具/技能/记忆管理页
fca9c1f chore: 更新记忆文件 + 记忆包说明
f5d43a1 docs: HTML 界面优化执行计划
2b4eec8 feat(ui): 管理层 + 侧边栏管理 Tab
8b5bc93 fix(security): 补全 ${} 变量展开拦截 + 测试用例
c5db59c docs: Phase 1 更新日志和安全操作说明
0ba70b9 feat(security): Phase 1 安全硬内核
```

### 25 项诊断修复率
- ✅ 无问题或已修：17 项
- ⚠️ 低风险架构债务：8 项

---

## 迭代计划状态

| Phase | 状态 | 说明 |
|-------|------|------|
| 1 安全硬内核 | ✅ 完成 | filesystem_guard + 命令白名单 + GUI 门控 |
| 2 工具插件化 | ⏳ 待做 | 40 工具拆为 10 个插件 + TOCTOU 修复 |
| 3 回滚事务化 | ⏳ 待做 | ACID 状态机 + ABORTED_BY_USER |
| 4 向量检索 | ⏳ 待做 | fastembed + sqlite-vec |
| 5 MCP Server | ⏳ 待做 | 有状态会话 + 协议冻结 |
| UI 管理层 | ✅ 完成 | manage/ 三层 + Streamlit 四 Tab |
| HTML 优化 | ✅ 完成 | Flask API + 前端 3 管理页 |
| Bug 修复 | ✅ 完成 | 17/25 已解决 |

---

## 关键教训

### 技术教训
1. **代码验证是最终裁判** — 老师的理论分析再漂亮，也得跑一遍代码验证
2. **GitHub TLS 不稳** — 服务器推代码经常断，需要重试
3. **token 安全** — 用户在聊天里发过 GitHub token，用完必须撤销
4. **on_confirm 必须有默认值** — 无回调时危险操作应拒绝而非静默通过
5. **截图 base64 要控制大小** — 超过 200KB 应存文件返回路径
6. **中文截断按行边界** — 不能按字节/字符截断，会切断多字节字符

### 协作教训
1. **用户 code review 很仔细** — 会看 YAML 格式、变量完整性
2. **用户要求"详细到可以直接执行"** — 不是伪代码，是完整可运行的代码
3. **用户时间有限** — "你我的时间快到期了" 时要快速打包记忆
4. **用户喜欢直接开干** — 说"开干"就别废话，直接写代码

---

## 下次继续

### 当前状态
- 仓库：`/root/.openclaw/workspace/YI-Agent-V1`
- 分支：`discipline-first`
- 最新 commit：`83f3059`
- 下一步：Phase 2 工具插件化 / 三入口统一 / 剩余架构债务

### 用户的工作流
1. 用户在 Windows 本地开发（F:\MyAgent\YI-Agent-V1）
2. 推送到 GitHub（Krat0sS/YI-Agent-V1）
3. 我在服务器上 clone 并修改
4. 推回 GitHub
5. 用户 pull 到本地

### ⚠️ 重要提醒
- GitHub TLS 不稳定，push 时可能需要重试
- 用户喜欢用 Streamlit 看效果，HTML 界面是补充
- `启动.bat` 已有完整的镜像+venv+启动逻辑，`start.bat` 新增了模式选择
