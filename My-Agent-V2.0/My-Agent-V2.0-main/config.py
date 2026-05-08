# -*- coding: utf-8 -*-
"""
配置中心 — 支持热更新

所有配置从 .env 文件读取，支持运行时热重载。
变量名全部用英文（跨平台兼容）。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

_project_dir = Path(__file__).parent.resolve()
_env_file = _project_dir / ".env"
load_dotenv(_env_file)


def _read_key(env_key="LLM_API_KEY"):
    """读取 API Key（过滤占位符）"""
    val = os.environ.get(env_key, "")
    return val if (val and not val.startswith("your-")) else ""


def _bool(val, default=True):
    """解析布尔值"""
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("true", "1", "yes") if val else default


# ═══════════════════════════════════════════════════════════
# LLM 配置
# ═══════════════════════════════════════════════════════════
LLM_API_KEY = _read_key()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "16384"))
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.3"))
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "30"))

# ═══════════════════════════════════════════════════════════
# Vision 模型（截图分析）
# ═══════════════════════════════════════════════════════════
VISION_API_KEY = os.environ.get("VISION_API_KEY", "")
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "")
VISION_MODEL = os.environ.get("VISION_MODEL", "")

# ═══════════════════════════════════════════════════════════
# Agent 行为
# ═══════════════════════════════════════════════════════════
AGENT_NAME = os.environ.get("AGENT_NAME", "My-Agent")
WORKSPACE = os.environ.get("WORKSPACE", os.path.expanduser("~/.my-agent/workspace"))
MEMORY_DIR = os.path.join(WORKSPACE, "memory")
MEMORY_FILE = os.path.join(WORKSPACE, "MEMORY.md")
SOUL_FILE = os.path.join(WORKSPACE, "SOUL.md")
LEARNED_PARAMS_FILE = os.path.join(WORKSPACE, "learned_params.json")
SESSIONS_DIR = os.path.join(WORKSPACE, "sessions")

MAX_TOOL_CALLS_PER_TURN = int(os.environ.get("MAX_TOOL_CALLS", "8"))
TOOL_TIMEOUT = float(os.environ.get("TOOL_TIMEOUT", "30"))

# 命令安全
BLOCKED_COMMANDS = []  # 黑名单命令（直接阻止）
CONFIRM_COMMANDS = [   # 需要确认的命令
    "playwright install",
    "npx playwright install",
]

# ═══════════════════════════════════════════════════════════
# 上下文管理
# ═══════════════════════════════════════════════════════════
MAX_CONTEXT_TURNS = int(os.environ.get("MAX_CONTEXT_TURNS", "20"))
OLD_MSG_MAX_LEN = int(os.environ.get("OLD_MSG_MAX_LEN", "800"))

# ═══════════════════════════════════════════════════════════
# 安全
# ═══════════════════════════════════════════════════════════
SECURITY_ENABLED = _bool(os.environ.get("SECURITY_ENABLED", "true"))
SECURITY_RATE_WINDOW = int(os.environ.get("SECURITY_RATE_WINDOW", "30"))
SECURITY_RATE_MAX_OPS = int(os.environ.get("SECURITY_RATE_MAX_OPS", "20"))
ALLOWED_PATHS = os.environ.get("ALLOWED_PATHS", "")  # 逗号分隔的额外允许路径

# ═══════════════════════════════════════════════════════════
# 记忆
# ═══════════════════════════════════════════════════════════
AUTO_MEMO = _bool(os.environ.get("AUTO_MEMO", "true"))
DAILY_LOG = _bool(os.environ.get("DAILY_LOG", "true"))
MEMORY_RETAIN_DAYS = int(os.environ.get("MEMORY_RETAIN_DAYS", "30"))

# ═══════════════════════════════════════════════════════════
# 浏览器
# ═══════════════════════════════════════════════════════════
GUI_CONFIRM = _bool(os.environ.get("GUI_CONFIRM", "true"))
AUTO_SCREENSHOT_VERIFY = _bool(os.environ.get("AUTO_SCREENSHOT_VERIFY", "true"))
ALLOWED_BROWSER_DOMAINS = [
    d.strip() for d in os.environ.get(
        "ALLOWED_DOMAINS", "github.com,arxiv.org,docs.python.org,localhost"
    ).split(",") if d.strip()
]

# ═══════════════════════════════════════════════════════════
# 技能系统
# ═══════════════════════════════════════════════════════════
AUTO_SKILL_PRECIPITATE = _bool(os.environ.get("AUTO_SKILL_PRECIPITATE", "true"))
SKILL_PRECIPITATE_THRESHOLD = int(os.environ.get("SKILL_PRECIPITATE_THRESHOLD", "3"))
TOOL_FALLBACK = _bool(os.environ.get("TOOL_FALLBACK", "true"))
BACKGROUND_OPTIMIZATION = _bool(os.environ.get("BACKGROUND_OPTIMIZATION", "true"))

# ═══════════════════════════════════════════════════════════
# Web Server
# ═══════════════════════════════════════════════════════════
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))


# ═══════════════════════════════════════════════════════════
# 热重载
# ═══════════════════════════════════════════════════════════

def reload_config():
    """热重载配置（从 .env 重新读取）"""
    global LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE, LLM_TIMEOUT
    global SECURITY_ENABLED, AUTO_MEMO, MAX_CONTEXT_TURNS, OLD_MSG_MAX_LEN
    global VISION_API_KEY, VISION_BASE_URL, VISION_MODEL
    global AUTO_SKILL_PRECIPITATE, SKILL_PRECIPITATE_THRESHOLD, TOOL_FALLBACK

    load_dotenv(_env_file, override=True)

    LLM_API_KEY = _read_key()
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
    LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
    LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "16384"))
    LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.3"))
    LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "30"))

    VISION_API_KEY = os.environ.get("VISION_API_KEY", "")
    VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "")
    VISION_MODEL = os.environ.get("VISION_MODEL", "")

    SECURITY_ENABLED = _bool(os.environ.get("SECURITY_ENABLED", "true"))
    AUTO_MEMO = _bool(os.environ.get("AUTO_MEMO", "true"))
    MAX_CONTEXT_TURNS = int(os.environ.get("MAX_CONTEXT_TURNS", "20"))
    OLD_MSG_MAX_LEN = int(os.environ.get("OLD_MSG_MAX_LEN", "800"))
    ALLOWED_PATHS = os.environ.get("ALLOWED_PATHS", "")

    AUTO_SKILL_PRECIPITATE = _bool(os.environ.get("AUTO_SKILL_PRECIPITATE", "true"))
    SKILL_PRECIPITATE_THRESHOLD = int(os.environ.get("SKILL_PRECIPITATE_THRESHOLD", "3"))
    TOOL_FALLBACK = _bool(os.environ.get("TOOL_FALLBACK", "true"))

    # 重置 LLM 客户端
    try:
        from core.llm import reset_client
        reset_client()
    except ImportError:
        pass

    print(f"[CONFIG] 已重载 | Model: {LLM_MODEL} | Security: {SECURITY_ENABLED}")


def to_dict():
    """导出配置（API Key 脱敏）"""
    return {
        "llm": {
            "apiKey": LLM_API_KEY[:8] + "***" if len(LLM_API_KEY) > 8 else "",
            "apiKeySet": bool(LLM_API_KEY),
            "baseUrl": LLM_BASE_URL,
            "model": LLM_MODEL,
            "maxTokens": LLM_MAX_TOKENS,
            "temperature": LLM_TEMPERATURE,
            "timeout": LLM_TIMEOUT,
        },
        "vision": {
            "apiKeySet": bool(VISION_API_KEY),
            "baseUrl": VISION_BASE_URL,
            "model": VISION_MODEL,
        },
        "agent": {
            "name": AGENT_NAME,
            "workspace": WORKSPACE,
            "maxToolCalls": MAX_TOOL_CALLS_PER_TURN,
            "maxContextTurns": MAX_CONTEXT_TURNS,
            "toolTimeout": TOOL_TIMEOUT,
        },
        "security": {
            "enabled": SECURITY_ENABLED,
            "rateWindow": SECURITY_RATE_WINDOW,
            "rateMaxOps": SECURITY_RATE_MAX_OPS,
            "allowedPaths": ALLOWED_PATHS,
        },
        "memory": {
            "autoMemo": AUTO_MEMO,
            "dailyLog": DAILY_LOG,
            "retainDays": MEMORY_RETAIN_DAYS,
        },
        "browser": {
            "guiConfirm": GUI_CONFIRM,
            "autoScreenshotVerify": AUTO_SCREENSHOT_VERIFY,
            "allowedDomains": ALLOWED_BROWSER_DOMAINS,
        },
        "skills": {
            "autoPrecipitate": AUTO_SKILL_PRECIPITATE,
            "precipitateThreshold": SKILL_PRECIPITATE_THRESHOLD,
            "toolFallback": TOOL_FALLBACK,
            "backgroundOptimization": BACKGROUND_OPTIMIZATION,
        },
    }
