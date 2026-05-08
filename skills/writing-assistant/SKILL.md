---
name: writing-assistant
version: "1.0"
description: 写作助手 — 文案撰写、润色改写、摘要提取、格式排版
trigger:
  keywords:
    - 写一篇
    - 帮我写
    - 润色
    - 改写
    - 摘要
    - 总结
    - 排版
    - 文章
    - 文案
    - 作文
    - write
    - polish
    - summarize
  exclude:
    - 代码
    - 搜索文件
    - git
    - 数据分析
tools: []
steps:
  - action: "明确写作目标：体裁、字数、风格、受众"
    description: "需求确认"
  - action: "生成大纲或直接撰写"
    description: "创作"
  - action: "检查逻辑连贯性、用词准确性、格式规范"
    description: "润色"
constraints:
  - "不编造事实和数据"
  - "正式文体避免口语化"
  - "技术文档保持准确性优先"
  - "用户给的参考资料必须引用"
rollback: null
---

# Writing Assistant 写作助手

## 使用场景
用户需要写文章、润色文案、提取摘要、整理格式。

## 支持体裁
- 技术文档 / README
- 商业邮件 / 正式信函
- 博客文章 / 社交媒体
- 会议纪要 / 工作总结
- 学术论文 / 报告

## 写作原则
1. 先理解目的和受众
2. 结构清晰：总分总
3. 用词精准，避免废话
4. 段落不超过 4 行

## 润色规则
- 删除冗余表达
- 统一术语和格式
- 检查逻辑跳跃
- 修正语法错误

## 注意事项
- 用户说"帮我写"但没给主题 → 问清楚
- 摘要控制在原文 20% 以内
- 翻译类需求引导到 translation 技能
