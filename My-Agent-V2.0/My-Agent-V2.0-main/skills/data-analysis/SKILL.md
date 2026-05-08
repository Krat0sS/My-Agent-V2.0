---
name: data-analysis
version: "1.0"
description: 数据分析 — CSV/JSON/Excel 数据探索、统计、可视化建议
trigger:
  keywords:
    - 数据分析
    - 统计
    - CSV
    - Excel
    - 数据
    - 图表
    - 可视化
    - data
    - analysis
    - 分析一下
  exclude:
    - 搜索
    - 网页
    - 桌面
    - 整理
tools:
  - read_file
  - run_command
  - list_files
steps:
  - action: "read_file 读取数据文件（CSV/JSON/Excel）"
    description: "加载数据"
  - action: "分析数据结构：列名、类型、缺失值、基本统计"
    description: "数据概览"
  - action: "根据用户需求执行分析：分组统计、趋势、相关性"
    description: "深度分析"
  - action: "输出结论 + 可视化建议（推荐图表类型）"
    description: "输出结果"
constraints:
  - "不自动修改原始数据文件"
  - "大数据集先采样分析"
  - "统计结论标注置信度"
  - "建议用 Python (pandas/matplotlib) 处理"
rollback: null
---

# Data Analysis 数据分析

## 使用场景
用户有 CSV/JSON/Excel 数据需要分析。

## 分析流程
1. 读取数据，识别结构
2. 数据概览：行数、列数、类型、缺失值
3. 基本统计：均值、中位数、分布
4. 深度分析：按用户需求分组、筛选、聚合
5. 输出结论 + 可视化建议

## 常用分析
- 描述性统计（mean/median/std）
- 分组聚合（groupby）
- 时间趋势（按日期排序）
- 相关性分析（corr）
- 异常值检测

## 注意事项
- 先问用户想分析什么，不要盲目跑统计
- 大文件先 `head` 看结构
- Python pandas 是首选工具
