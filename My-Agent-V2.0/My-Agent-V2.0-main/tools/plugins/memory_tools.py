"""
记忆工具插件 — remember / recall / set_preference
从 builtin.py 拆分，自注册到 ToolRegistry
"""
import os
import re
import json
import difflib
import datetime
from tools.registry import registry
from tools.tool_utils import ToolResult


def _check_jieba():
    try:
        import jieba
        return True
    except ImportError:
        return False


def _remember(content: str) -> str:
    import config
    try:
        os.makedirs(os.path.dirname(config.MEMORY_FILE), exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n\n### {timestamp}\n{content}\n"
        with open(config.MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
        return ToolResult.ok({"message": "已保存到长期记忆", "timestamp": timestamp})
    except Exception as e:
        return ToolResult.fail(f"保存记忆失败: {e}", "E_MEMORY_WRITE",
                               recoverable=True, hint="检查文件权限和磁盘空间。")


def _recall(query: str) -> str:
    import config
    if not os.path.exists(config.MEMORY_FILE):
        return ToolResult.ok({"result": "暂无长期记忆", "matches": 0})

    with open(config.MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        return ToolResult.ok({"result": "暂无长期记忆", "matches": 0})

    sections = []
    current = ""
    for line in content.split("\n"):
        if line.startswith("### ") and current.strip():
            sections.append(current.strip())
            current = line + "\n"
        else:
            current += line
    if current.strip():
        sections.append(current.strip())

    if not sections:
        return json.dumps({"result": content[-3000:]})

    try:
        import jieba
        def tokenize(text: str) -> list[str]:
            words = jieba.lcut(text.lower())
            return [w for w in words if len(w) > 1 and not w.isdigit() and not re.match(r'^[\s\W]+$', w)]
        query_tokens = tokenize(query)
    except ImportError:
        def tokenize(text: str) -> list[str]:
            return [w for w in text.lower().split() if len(w) > 1]
        query_tokens = tokenize(query)

    query_lower = query.lower()
    scored = []
    for section in sections:
        section_lower = section.lower()
        section_tokens = tokenize(section)
        seq_score = difflib.SequenceMatcher(None, query_lower, section_lower).ratio()

        if query_tokens and section_tokens:
            section_set = set(section_tokens)
            token_hits = sum(1 for t in query_tokens if t in section_set)
            token_score = token_hits / len(query_tokens)
        else:
            token_score = 0

        keyword_hits = sum(1 for kw in query_lower.split() if kw in section_lower)
        keyword_score = keyword_hits / max(len(query_lower.split()), 1)
        total_score = seq_score * 0.2 + token_score * 0.5 + keyword_score * 0.3
        scored.append((total_score, section))

    scored.sort(reverse=True, key=lambda x: x[0])

    results = []
    total_len = 0
    for score, section in scored[:5]:
        if score < 0.05:
            continue
        if total_len + len(section) > 4000:
            break
        results.append(section)
        total_len += len(section)

    return ToolResult.ok({
        "query": query,
        "query_tokens": query_tokens,
        "matches": len(results),
        "result": "\n\n---\n\n".join(results) if results else "未找到相关记忆。",
    })


def _set_preference(key: str, value: str) -> str:
    from memory.memory_system import MemorySystem
    try:
        memory = MemorySystem()
        old_value = memory.learned_params.get(key, "(未设置)")
        memory.update_param(key, value)
        return ToolResult.ok({
            "key": key, "old_value": old_value, "new_value": value,
            "message": f"已更新偏好：{key} = {value}",
        })
    except Exception as e:
        return ToolResult.fail(f"设置偏好失败: {e}", "E_MEMORY_WRITE",
                               recoverable=True)


registry.register(
    name="remember",
    description="保存重要信息到长期记忆",
    schema={
        "name": "remember",
        "description": "保存重要信息到长期记忆",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容"}
            },
            "required": ["content"]
        }
    },
    handler=_remember,
    category="memory",
    risk_level="medium",
)


registry.register(
    name="recall",
    description="检索长期记忆（语义模糊匹配）",
    schema={
        "name": "recall",
        "description": "检索长期记忆。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要回忆的内容关键词或描述"}
            },
            "required": ["query"]
        }
    },
    handler=_recall,
    category="memory",
    check_fn=_check_jieba,
    risk_level="low",
)


registry.register(
    name="set_preference",
    description="设置用户偏好参数（如 verbosity, style 等），会持久化并在后续对话中生效",
    schema={
        "name": "set_preference",
        "description": "设置用户偏好参数。",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "参数名"},
                "value": {"type": "string", "description": "参数值"}
            },
            "required": ["key", "value"]
        }
    },
    handler=_set_preference,
    category="memory",
    risk_level="medium",
)
