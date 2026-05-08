---
name: git-workflow
version: "1.0"
description: Git 工作流自动化 — 提交、推送、分支管理、冲突解决
trigger:
  keywords:
    - git
    - 提交
    - commit
    - push
    - 推送
    - 分支
    - branch
    - merge
    - 合并
    - pull request
    - PR
    - 版本控制
  exclude:
    - 搜索
    - 网页
    - 天气
    - 文件搜索
tools:
  - git_status
  - git_diff
  - git_add
  - git_commit
  - git_push
  - run_command
steps:
  - action: "git_status 查看当前状态"
    description: "检查状态"
  - action: "git_diff 查看变更内容"
    description: "查看差异"
  - action: "git_add 添加变更文件"
    description: "暂存文件"
  - action: "git_commit(message={commit_message})"
    description: "提交"
  - action: "git_push 推送到远程"
    description: "推送"
constraints:
  - "push 前必须先 diff 让用户确认"
  - "不自动 force push"
  - "commit message 用中文，简洁描述改动"
  - "有冲突时展示冲突内容，不自动解决"
rollback: "git_restore"
---

# Git Workflow 自动化

## 使用场景
用户写完代码想提交推送，或需要管理分支。

## 标准流程
1. `git status` 看状态
2. `git diff` 看改了什么
3. 用户确认后 `git add`
4. 自动生成 commit message 并提交
5. 用户确认后推送

## 注意事项
- push 是危险操作，必须用户确认
- commit message 格式：`类型: 简要描述`（feat/fix/docs/refactor）
- 有未提交的更改时提醒用户先处理
