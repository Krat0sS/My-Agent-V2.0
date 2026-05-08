---
name: desktop-organize
version: "1.0"
description: 整理桌面/下载文件夹的文件，自动分类归档
trigger:
  keywords:
    - 整理
    - 清理
    - 归类
    - 收拾
    - 桌面
    - 乱
    - organize
    - clean
  exclude:
    - 搜索结果
    - 网页
    - 浏览器
    - 在线
    - 数据
tools:
  - scan_files
  - organize_directory
  - rollback_operation
steps:
  - action: "scan_files(path={target})"
    description: "扫描目标目录"
  - action: "检查文件数，<5个则告知无需整理"
    description: "判断是否需要整理"
  - action: "organize_directory(path={target}, dry_run=True)"
    description: "预览分类方案"
  - action: "organize_directory(path={target})"
    description: "执行分类移动"
  - action: "汇报结果：分类数、文件数、不确定文件"
    description: "告知用户结果"
  - action: "提示：说'恢复'可一键撤销"
    description: "提供回滚入口"
constraints:
  - "不删除任何文件"
  - "不整理系统目录（/usr, /etc）"
  - "文件名冲突时两个都保留（重命名）"
  - "不确定分类单独列出"
rollback: "rollback_operation"
---

# Desktop Organize 技能

## 使用场景
用户桌面或下载文件夹太乱，需要整理文件。

## 执行逻辑
1. scan_files 扫描目标目录
2. 文件数 < 5 告知无需整理
3. organize_directory 预览模式展示方案
4. 确认后执行分类
5. 汇报结果，提示可回滚

## 注意事项
- 不删除文件
- 不确定分类单独列出，请用户决定
- 有 .git 的目录跳过不处理
