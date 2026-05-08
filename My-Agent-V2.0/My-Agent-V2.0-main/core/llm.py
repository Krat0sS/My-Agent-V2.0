# -*- coding: utf-8 -*-
"""
LLM 调用封装 — 统一走 OpenAI 兼容接口

支持：DeepSeek / OpenAI / 通义千问 / 智谱 GLM / Kimi / MiMo 等
删除：Ollama 本地模型（不可靠的 function calling）

v2.1 修复：
- httpx.AsyncClient 替代同步 Client（不阻塞事件循环）
- 超时提升到 120 秒（复杂任务需要更长时间）
- 自动重试 1 次（处理瞬时网络错误）
"""

import json
import time
import httpx
import config
import logging

logger = logging.getLogger("llm")

_client = None


def _get_client():
    """获取 httpx 异步客户端（单例）"""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=config.LLM_BASE_URL,
            headers={
                "Authorization": f"Bearer {config.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(
                connect=10.0,
                read=120.0,    # LLM 生成可能很慢
                write=10.0,
                pool=5.0,
            ),
        )
    return _client


def reset_client():
    """配置变更后重置客户端（热更新用）"""
    global _client
    _client = None


async def chat(messages: list, tools: list = None, **kwargs) -> dict:
    """
    统一 LLM 调用（OpenAI 兼容格式）

    Args:
        messages: 对话历史
        tools: OpenAI function calling schema（可选）
        **kwargs: 其他参数（temperature 等）

    Returns:
        dict: 至少包含 "content"，可能包含 "tool_calls"、"_usage"
    """
    client = _get_client()

    payload = {
        "model": kwargs.get("model", config.LLM_MODEL),
        "messages": messages,
        "max_tokens": kwargs.get("max_tokens", config.LLM_MAX_TOKENS),
        "temperature": kwargs.get("temperature", config.LLM_TEMPERATURE),
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    # 自动重试 1 次（处理瞬时网络错误）
    max_retries = 2
    last_err = None

    for attempt in range(max_retries):
        try:
            resp = await client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()

            choice = data["choices"][0]
            result = choice["message"]

            # 附加 usage 信息
            if "usage" in data:
                result["_usage"] = data["usage"]

            return result

        except httpx.TimeoutException as e:
            last_err = e
            if attempt < max_retries - 1:
                logger.warning(f"LLM 超时，重试 {attempt + 1}/{max_retries - 1}")
                continue
            return {
                "content": "❌ LLM 调用超时（120秒），请检查网络或 API 配置",
                "_timeout": True,
            }
        except httpx.HTTPStatusError as e:
            last_err = e
            status = e.response.status_code
            resp_text = ""
            try:
                resp_text = e.response.text[:500]
            except Exception:
                pass
            # 429/502/503 可重试
            if status in (429, 502, 503) and attempt < max_retries - 1:
                logger.warning(f"LLM HTTP {status}，重试 {attempt + 1}/{max_retries - 1}")
                import asyncio
                await asyncio.sleep(2 * (attempt + 1))
                continue
            # 400 + token/context 相关 → 标记 _context_overflow 让调用方截断重试
            if status == 400 and any(kw in resp_text.lower() for kw in
                    ("token", "context", "length", "maximum", "exceed")):
                logger.warning(f"LLM 上下文过长 (HTTP 400)，标记 _context_overflow")
                return {
                    "content": f"❌ 上下文过长，需要截断重试",
                    "_error": True,
                    "_context_overflow": True,
                }
            return {
                "content": f"❌ LLM API 错误: HTTP {status}",
                "_error": True,
            }
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                logger.warning(f"LLM 异常，重试: {e}")
                import asyncio
                await asyncio.sleep(1)
                continue
            return {
                "content": f"❌ LLM 调用失败: {str(e)}",
                "_error": True,
            }

    return {
        "content": f"❌ LLM 调用失败: {str(last_err)}",
        "_error": True,
    }


def chat_simple_sync(system: str, prompt: str, **kwargs) -> str:
    """同步版简单对话（供搜索摘要等同步上下文使用）"""
    import asyncio
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    coro = chat(messages, **kwargs)

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            new_loop = asyncio.new_event_loop()
            try:
                result = new_loop.run_until_complete(coro)
            finally:
                new_loop.close()
    else:
        result = asyncio.run(coro)

    if result.get("_error") or result.get("_timeout"):
        return result.get("content", "LLM 调用失败")
    return result.get("content", "")


def chat_simple(prompt: str, **kwargs) -> dict:
    """简单对话（无工具）— 同步版本（兼容旧代码）"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    coro = chat([{"role": "user", "content": prompt}], **kwargs)

    if loop and loop.is_running():
        # 在异步上下文中，创建新事件循环执行
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()
    else:
        return asyncio.run(coro)
