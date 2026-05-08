---
name: file-search
version: "1.0"
description: 在本地文件系统中搜索文件（按名称、类型、日期、大小筛选）
trigger:
  keywords:
    - 查找文件
    - 找文件
    - 搜索文件
    - 文件在哪
    - find files
    - search files
    - PDF
    - Word
    - Excel
    - 图片
    - 视频
  exclude:
    - 百度
    - Google
    - Bing
    - 网页
    - 浏览器
    - 网站
    - 天气
    - 新闻
    - 股票
    - 在线
    - 搜索引擎
    - 搜一下
    - 帮我搜
tools:
  - find_files
  - scan_files
steps:
  - action: "从用户输入提取搜索条件：关键词、扩展名、日期、大小"
    description: "解析条件"
  - action: "find_files(query={keywords}, path={target_dir})"
    description: "执行搜索"
  - action: "如果结果为空，放宽条件再搜一次"
    description: "重试"
  - action: "将结果按时间线或分类组织展示"
    description: "展示结果"
constraints:
  - "搜索路径不从根目录开始，先确认目录"
  - "结果超过50个分页展示"
  - "搜索隐藏文件需用户明确要求"
  - "用户提到网页/浏览器/天气等词时拒绝执行"
rollback: null
---

# File Search 技能

## 使用场景
用户需要在本地找某个文件，按名称、类型、日期等条件搜索。

## 执行逻辑
1. 解析用户搜索条件
2. find_files 执行搜索
3. 结果为空则放宽条件重试
4. 按时间线或分类展示结果

## 注意事项
- 仅限本地文件搜索，不适用于网页搜索
- 用户提到"百度""网页""浏览器"等词时，这不是文件搜索任务
