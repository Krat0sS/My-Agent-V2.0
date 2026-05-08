---
name: code-review
version: "1.0"
description: 代码审查 — 检查 Bug、安全漏洞、性能问题、代码规范
trigger:
  keywords:
    - 代码审查
    - review
    - 检查代码
    - 看看代码
    - 代码有问题吗
    - 帮我看看
    - code review
    - 查错
    - 排查
  exclude:
    - 搜索
    - 天气
    - 桌面
    - 整理文件
tools:
  - read_file
  - list_files
  - scan_files
steps:
  - action: "确定要审查的文件或目录路径"
    description: "定位目标"
  - action: "read_file(path={target}) 或 scan_files 扫描目录"
    description: "读取代码"
  - action: "逐文件分析：Bug 风险、安全漏洞、性能瓶颈、命名规范、重复代码"
    description: "深度审查"
  - action: "按严重程度分级输出：🔴 严重 / 🟡 警告 / 🔵 建议"
    description: "输出报告"
constraints:
  - "不修改代码，只输出审查报告"
  - "每个问题标注文件名和行号"
  - "给出具体修复建议，不只说'这里有问题'"
  - "大文件先扫描结构再逐模块审查"
rollback: null
---

# Code Review 代码审查

## 使用场景
用户写了一段代码想检查，或提交前做最后审查。

## 审查维度
1. **Bug 风险** — 空指针、越界、类型错误、逻辑漏洞
2. **安全漏洞** — 注入、硬编码密钥、不安全的输入处理
3. **性能问题** — N+1 查询、不必要的循环、内存泄漏
4. **代码规范** — 命名一致性、函数长度、注释质量
5. **可维护性** — 重复代码、耦合度、测试覆盖

## 输出格式
```
🔴 严重：[文件:行号] 问题描述
   修复建议：具体方案

🟡 警告：[文件:行号] 问题描述
   建议：改进方向

🔵 建议：[文件:行号] 优化点
```

## 注意事项
- 先理解项目上下文再审查
- 不要吹毛求疵，关注真正有影响的问题
- Python / JavaScript / TypeScript / Go / Java 均支持
