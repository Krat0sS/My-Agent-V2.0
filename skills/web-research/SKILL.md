---
name: web-research
version: "1.0"
description: 联网搜索并提取网页内容
trigger:
  keywords:
    - 搜索
    - 查找
    - 研究
    - 调研
    - 最新
    - 了解
    - search
    - find
    - research
  exclude:
    - 桌面
    - 本地文件
    - 文件夹
    - 目录
tools:
  - web_search
  - ab_open
  - ab_get_text
  - remember
steps:
  - action: "web_search(query={query})"
    description: "搜索关键词"
  - action: "ab_open(url={result_url})"
    description: "打开搜索结果页面"
  - action: "ab_get_text(selector=body)"
    description: "提取页面文本内容"
constraints:
  - "不猜测URL，必须先搜索"
  - "搜索失败时换关键词重试"
  - "结果标注来源URL"
rollback: null
---

# Web Research 技能

## 使用场景
用户需要搜索联网信息、调研某个话题、了解最新动态。

## 执行逻辑
1. 用 web_search 搜索用户关键词
2. 从结果中选最相关的 1-3 条
3. 用 ab_open 打开页面，ab_get_text 提取内容
4. 汇总信息回复用户，标注来源

## 注意事项
- 不要用知识替代搜索（信息可能过时）
- 搜索失败时换关键词重试
- 结果用 [MEMO:] 标记值得记忆的信息
