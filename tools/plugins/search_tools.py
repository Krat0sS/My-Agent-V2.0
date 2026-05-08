"""
搜索工具插件 — web_search / news_search
从 builtin.py 拆分，自注册到 ToolRegistry
"""
import json
from tools.registry import registry
from tools.tool_utils import ToolResult


def _check_duckduckgo():
    try:
        from ddgs import DDGS
        return True
    except ImportError:
        pass
    try:
        from duckduckgo_search import DDGS
        return True
    except ImportError:
        return False


def _web_search(query: str, objective: str = "", max_results: int = 5) -> str:
    from tools.search import search_and_summarize_sync
    try:
        result = search_and_summarize_sync(query, max_results=max_results, objective=objective)
        if isinstance(result, dict) and result.get("error"):
            return ToolResult.fail(result["error"], "E_SEARCH_FAILED",
                                   hint="搜索被限流或网络异常，稍后重试或换个关键词。")
        return ToolResult.ok(result if isinstance(result, dict) else {"summary": result})
    except Exception as e:
        return ToolResult.fail(f"搜索失败: {e}", "E_SEARCH_FAILED",
                               recoverable=True, hint="检查网络连接，或换个关键词重试。")


def _news_search(query: str, max_results: int = 5) -> str:
    from tools.search import news_search_sync
    try:
        result = news_search_sync(query, max_results=max_results)
        if isinstance(result, dict) and result.get("error"):
            return ToolResult.fail(result["error"], "E_SEARCH_FAILED",
                                   hint="新闻搜索失败，稍后重试。")
        return ToolResult.ok(result if isinstance(result, dict) else {"summary": result})
    except Exception as e:
        return ToolResult.fail(f"新闻搜索失败: {e}", "E_SEARCH_FAILED",
                               recoverable=True, hint="检查网络连接后重试。")


registry.register(
    name="web_search",
    description="真实联网搜索（DuckDuckGo）。返回搜索结果摘要和链接。适用于查找最新信息、文档、教程、新闻等。",
    schema={
        "name": "web_search",
        "description": "真实联网搜索（DuckDuckGo）。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，建议用英文关键词效果更好"},
                "objective": {"type": "string", "description": "你希望从搜索结果中提取什么", "default": ""},
                "max_results": {"type": "integer", "description": "最大结果数", "default": 5}
            },
            "required": ["query"]
        }
    },
    handler=_web_search,
    category="search",
    check_fn=_check_duckduckgo,
    risk_level="low",
)


registry.register(
    name="news_search",
    description="搜索新闻。用于查找最新事件、行业动态、产品发布等时效性信息。",
    schema={
        "name": "news_search",
        "description": "搜索新闻。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "新闻搜索关键词"},
                "max_results": {"type": "integer", "description": "最大结果数", "default": 5}
            },
            "required": ["query"]
        }
    },
    handler=_news_search,
    category="search",
    check_fn=_check_duckduckgo,
    risk_level="low",
)
