<div align="center">

# 🤖 My-Agent V2.0

**个人 AI Agent 框架 — 意图路由 + 工具生态 + 技能沉淀**

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-Compatible-orange)](https://deepseek.com)

*一个能理解你说什么、自己决定怎么做、做完会记住经验的 AI Agent。*

</div>

---

## ✨ 它能做什么

你只需要说一句话，剩下的交给它：

> "帮我搜一下最近 AI 领域有什么新论文，整理成摘要发给我"

它会自己拆解任务 → 搜索 → 筛选 → 整理 → 输出结果。中间每一步都有清晰的思考过程展示，你能看到它在想什么、在做什么。

**不是聊天机器人，是真正能干活的智能体。**

---

## 🏗️ 架构设计

```
用户输入
   ↓
 意图理解 ← 一次判断，一条路径
   ├─ 🎯 技能命中 → 秒级执行（已有经验）
   ├─ 📐 模板匹配 → 零推理直接跑（高频场景）
   ├─ 📝 任务分解 → 自动拆步骤 → 按序执行
   └─ 💬 智能对话 → 工具调用 + 自然语言
```

**设计哲学：少即是多。** 一个决策入口，一条执行路径，不纠结，不打架。

---

## 🧠 自我优化

Agent 执行过程中会自动积累经验：

| 能力 | 实现方式 | 效果 |
|:---:|------|------|
| **工具效果追踪** | SQLite 记录每次调用的成功/失败/耗时，双窗口加权评分 | 越用越准，自动选择最佳工具 |
| **技能沉淀** | 重复任务自动生成 SKILL.md，BM25 语义去重 | 第一次走分解，第二次直接命中技能 |
| **用户偏好记忆** | `[MEMO:]` 标记自动提取，跨会话持久化 | 记住你的习惯 |
| **运行时自优化** | 统计高频失败工具 → 自动降低可用性评分、补降级链 | 减少无效调用 |

---

## 🔒 安全体系

不是事后补丁，是设计内建：

- **命令三级分类** — 只读放行 / 写入记录 / 危险拦截
- **Git 精确管控** — `status` 自由，`push` 确认，`--force` 双重确认
- **路径白名单** — 敏感路径硬编码拒绝（`/etc/shadow`、`authorized_keys`）
- **命令注入检测** — `;|&` 等危险字符自动阻断
- **频率熔断** — 滑动窗口限流，防失控
- **审计日志** — SQLite 持久化，每次操作可追溯

---

## 🎨 实时思考过程

像 DeepSeek 一样，你能看到 Agent 的每一步思考：

```
▸ 已思考 16 秒
  ✅ 理解意图
     分析用户意图：「帮我搜索今天的天气」
     判断为中等复杂度任务，直接调用工具完成
  ✅ 打开网页                              446ms
     打开网址：https://bing.com/search?q=...
     → 已打开页面
  ✅ 执行命令                              1200ms
     执行命令：playwright install chromium
     → 安装完成
```

还有**节点浏览**视图，用时间线展示整个执行流程，每个节点可展开查看详情。

---

## 🔧 内置工具（62 个）

| 类别 | 工具 |
|------|------|
| 🌐 浏览器 | 打开网页、点击、填写、截图、执行 JS、快照...（Playwright 驱动，14 个） |
| 🔍 搜索 | 联网搜索、DuckDuckGo |
| 📂 文件 | 读写、编辑、扫描、搜索、移动、批量操作、整理、回滚 |
| ⚡ 命令 | 安全的命令执行（三级权限控制 + 命令注入检测） |
| 📦 Git | status、diff、add、commit、push、restore（子命令级精确管控） |
| 🧠 记忆 | 记住、回忆、偏好管理 |
| 📸 视觉 | 截图分析、视觉理解 |
| 🔧 系统 | 文件监控、变量管理、任务规划 |

工具不可用时自动降级（`web_search` → `浏览器搜索`），确保任务不中断。

---

## 🚀 快速开始

```bash
# 克隆项目
git clone https://github.com/Krat0sS/My-Agent-V2.0.git
cd My-Agent-V2.0

# 安装依赖
pip install -r requirements.txt

# 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 LLM_API_KEY

# 启动
python server.py --port 8080
```

打开浏览器访问 `http://localhost:8080`，开始对话。

支持开箱即用的模型：DeepSeek / MiMo / GPT-4o / Claude / 通义千问 / 智谱 GLM / Kimi。

---

## 📁 项目结构

```
My-Agent-V2.0/
├── core/                    # 核心引擎
│   ├── conversation.py      # 主循环 + 四路径执行
│   ├── intent_router.py     # 意图路由（BM25 + LLM 精排）
│   ├── llm.py               # LLM 统一调用层
│   ├── workflow.py           # 工作流执行器
│   └── self_optimizer.py    # 自我优化引擎
├── skills/                  # 技能系统（YAML frontmatter + 自动沉淀）
├── tools/                   # 工具层（自动注册 + 降级链）
├── security/                # 安全模块（命令/路径/频率/审计）
├── yi_framework/            # 效果评估（双窗口加权）
├── server.py                # Web API（SSE 流式 + 29 个端点）
├── index.html               # 前端（思考过程 + 节点浏览 + 6 个管理页面）
└── 启动.py                  # 一键启动器
```

---

## 📡 API

| 方法 | 路径 | 说明 |
|:---:|------|------|
| `POST` | `/api/chat` | 对话（会话锁 + 过期清理） |
| `POST` | `/api/chat/stream` | SSE 流式对话（实时思考过程） |
| `POST` | `/api/chat/reset` | 重置会话 |
| `GET` | `/api/tools` | 工具列表 |
| `POST` | `/api/tools/{name}/toggle` | 工具开关 |
| `GET/CRUD` | `/api/skills` | 技能管理 |
| `GET` | `/api/memory` | 记忆列表 |
| `GET` | `/api/permissions` | 权限配置 |
| `GET` | `/api/permissions/audit-log` | 审计日志 |
| `GET/PUT` | `/api/settings/full` | 完整配置（热重载） |
| `GET` | `/api/diagnostics` | 系统诊断 |

---

## 🛠️ 技术栈

`Python` · `Flask` · `SQLite (WAL)` · `Playwright` · `BM25` · `OpenAI Compatible API`

---

## 📄 许可证

[MIT License](LICENSE)
