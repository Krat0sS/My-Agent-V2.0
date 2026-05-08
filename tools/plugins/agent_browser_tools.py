"""
浏览器自动化工具插件（Playwright 驱动）

使用 Playwright Python API 直接控制浏览器，无需 CLI 工具。
支持 accessibility snapshot（@ref 元素引用）、截图、JS 执行等。

安装：pip install playwright && playwright install chromium
"""
import json
from tools.registry import registry


def _check_agent_browser():
    try:
        from tools.agent_browser import is_available
        return is_available()
    except ImportError:
        return False


# ═══ 工具定义 ═══

def _ab_open(url: str) -> str:
    from tools.agent_browser import ab_open
    r = ab_open(url)
    return json.dumps(r, ensure_ascii=False)


def _ab_snapshot(interactive: bool = False, full: bool = False) -> str:
    from tools.agent_browser import ab_snapshot
    r = ab_snapshot(interactive, full)
    return json.dumps(r, ensure_ascii=False)


def _ab_click(selector: str) -> str:
    from tools.agent_browser import ab_click
    r = ab_click(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_fill(selector: str, text: str) -> str:
    from tools.agent_browser import ab_fill
    r = ab_fill(selector, text)
    return json.dumps(r, ensure_ascii=False)


def _ab_type(selector: str, text: str) -> str:
    from tools.agent_browser import ab_type
    r = ab_type(selector, text)
    return json.dumps(r, ensure_ascii=False)


def _ab_press(key: str) -> str:
    from tools.agent_browser import ab_press
    r = ab_press(key)
    return json.dumps(r, ensure_ascii=False)


def _ab_screenshot(path: str = None, full_page: bool = False, annotate: bool = False) -> str:
    from tools.agent_browser import ab_screenshot
    r = ab_screenshot(path, full_page, annotate)
    return json.dumps(r, ensure_ascii=False)


def _ab_get_text(selector: str) -> str:
    from tools.agent_browser import ab_get_text
    r = ab_get_text(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_eval(js: str) -> str:
    from tools.agent_browser import ab_eval
    r = ab_eval(js)
    return json.dumps(r, ensure_ascii=False)


def _ab_wait(selector: str = None, text: str = None, timeout_ms: int = 10000) -> str:
    from tools.agent_browser import ab_wait
    r = ab_wait(selector=selector, text=text, timeout_ms=timeout_ms)
    return json.dumps(r, ensure_ascii=False)


def _ab_find(by: str, value: str, action: str = "click") -> str:
    from tools.agent_browser import ab_find
    r = ab_find(by, value, action)
    return json.dumps(r, ensure_ascii=False)


def _ab_scroll(direction: str, pixels: int = 300) -> str:
    from tools.agent_browser import ab_scroll
    r = ab_scroll(direction, pixels)
    return json.dumps(r, ensure_ascii=False)


def _ab_hover(selector: str) -> str:
    from tools.agent_browser import ab_hover
    r = ab_hover(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_select(selector: str, value: str) -> str:
    from tools.agent_browser import ab_select
    r = ab_select(selector, value)
    return json.dumps(r, ensure_ascii=False)


def _ab_close() -> str:
    from tools.agent_browser import ab_close
    r = ab_close()
    return json.dumps(r, ensure_ascii=False)


def _ab_navigate_and_snapshot(url: str) -> str:
    from tools.agent_browser import ab_navigate_and_snapshot
    r = ab_navigate_and_snapshot(url)
    return json.dumps(r, ensure_ascii=False)


def _ab_is_visible(selector: str) -> str:
    from tools.agent_browser import ab_is_visible
    r = ab_is_visible(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_get_html(selector: str) -> str:
    from tools.agent_browser import ab_get_html
    r = ab_get_html(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_get_value(selector: str) -> str:
    from tools.agent_browser import ab_get_value
    r = ab_get_value(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_get_attr(selector: str, attr: str) -> str:
    from tools.agent_browser import ab_get_attr
    r = ab_get_attr(selector, attr)
    return json.dumps(r, ensure_ascii=False)


def _ab_get_title() -> str:
    from tools.agent_browser import ab_get_title
    r = ab_get_title()
    return json.dumps(r, ensure_ascii=False)


def _ab_get_url() -> str:
    from tools.agent_browser import ab_get_url
    r = ab_get_url()
    return json.dumps(r, ensure_ascii=False)


def _ab_pdf(path: str) -> str:
    from tools.agent_browser import ab_pdf
    r = ab_pdf(path)
    return json.dumps(r, ensure_ascii=False)


def _ab_scrollintoview(selector: str) -> str:
    from tools.agent_browser import ab_scrollintoview
    r = ab_scrollintoview(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_dblclick(selector: str) -> str:
    from tools.agent_browser import ab_dblclick
    r = ab_dblclick(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_check(selector: str) -> str:
    from tools.agent_browser import ab_check
    r = ab_check(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_uncheck(selector: str) -> str:
    from tools.agent_browser import ab_uncheck
    r = ab_uncheck(selector)
    return json.dumps(r, ensure_ascii=False)


def _ab_drag(source: str, target: str) -> str:
    from tools.agent_browser import ab_drag
    r = ab_drag(source, target)
    return json.dumps(r, ensure_ascii=False)


def _ab_connect(port: int = 9222) -> str:
    from tools.agent_browser import ab_connect
    r = ab_connect(port)
    return json.dumps(r, ensure_ascii=False)


# ═══ 注册工具 ═══

# 核心工具（高频使用）
registry.register(
    name="ab_open",
    description="用 Playwright 打开网页。支持 @ref 元素引用。",
    schema={
        "name": "ab_open",
        "description": "用 Playwright 打开网页。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "网页地址（完整 URL）"}
            },
            "required": ["url"]
        }
    },
    handler=_ab_open,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_snapshot",
    description="获取页面快照。默认返回轻量 url+title+page_text（前500字），LLM 可判断页面内容。full=True 返回完整 @ref 元素树（用于精确操作）。",
    schema={
        "name": "ab_snapshot",
        "description": "获取页面快照。默认轻量模式返回页面文本摘要，full=True 返回完整元素树。",
        "parameters": {
            "type": "object",
            "properties": {
                "interactive": {"type": "boolean", "description": "是否返回精简交互版", "default": False},
                "full": {"type": "boolean", "description": "True 返回完整 @ref 元素树，False 返回轻量 page_text", "default": False}
            }
        }
    },
    handler=_ab_snapshot,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_click",
    description="用 Playwright 点击元素。支持 CSS 选择器和 @ref（如 @e2）。",
    schema={
        "name": "ab_click",
        "description": "点击页面元素。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "元素选择器（CSS 或 @ref 如 @e2）"},
                "new_tab": {"type": "boolean", "description": "是否在新标签页打开", "default": False}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_click,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_fill",
    description="用 Playwright 清空并填写文本到输入框。支持 @ref 选择器。",
    schema={
        "name": "ab_fill",
        "description": "清空并填写文本到输入框。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "输入框选择器（CSS 或 @ref）"},
                "text": {"type": "string", "description": "要填写的文本"}
            },
            "required": ["selector", "text"]
        }
    },
    handler=_ab_fill,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_type",
    description="用 Playwright 逐字输入文本（模拟键盘）。",
    schema={
        "name": "ab_type",
        "description": "逐字输入文本（模拟键盘）。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "输入框选择器"},
                "text": {"type": "string", "description": "要输入的文本"}
            },
            "required": ["selector", "text"]
        }
    },
    handler=_ab_type,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_press",
    description="按下键盘按键。支持 Enter/Tab/Escape/Backspace/ctrl+a/ctrl+c 等。",
    schema={
        "name": "ab_press",
        "description": "按下键盘按键。",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "按键名，如 Enter/Tab/Escape/ctrl+a"}
            },
            "required": ["key"]
        }
    },
    handler=_ab_press,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_screenshot",
    description="用 Playwright 截图。支持全页截图。",
    schema={
        "name": "ab_screenshot",
        "description": "截取浏览器页面截图。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "保存路径（不传则保存到临时目录）"},
                "full_page": {"type": "boolean", "description": "是否截取整个页面", "default": False},
                "annotate": {"type": "boolean", "description": "是否标注元素编号（AI 友好）", "default": False}
            }
        }
    },
    handler=_ab_screenshot,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_snapshot_click",
    description="打开网页并获取可访问性快照（组合命令，最常用）。先 open 再 snapshot。",
    schema={
        "name": "ab_snapshot_click",
        "description": "打开网页并获取可访问性快照。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "网页地址"}
            },
            "required": ["url"]
        }
    },
    handler=_ab_navigate_and_snapshot,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

# 辅助工具
registry.register(
    name="ab_get_text",
    description="获取页面元素的文本内容。支持 @ref 选择器。",
    schema={
        "name": "ab_get_text",
        "description": "获取元素文本内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "元素选择器（CSS 或 @ref）"}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_get_text,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_get_html",
    description="获取元素的 innerHTML。",
    schema={
        "name": "ab_get_html",
        "description": "获取元素 innerHTML。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "元素选择器"}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_get_html,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_get_value",
    description="获取输入框的当前值。",
    schema={
        "name": "ab_get_value",
        "description": "获取输入框值。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "输入框选择器"}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_get_value,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_get_attr",
    description="获取元素的指定属性值。",
    schema={
        "name": "ab_get_attr",
        "description": "获取元素属性值。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "元素选择器"},
                "attr": {"type": "string", "description": "属性名（如 href/src/class/id）"}
            },
            "required": ["selector", "attr"]
        }
    },
    handler=_ab_get_attr,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_get_title",
    description="获取当前页面标题。",
    schema={
        "name": "ab_get_title",
        "description": "获取页面标题。",
        "parameters": {"type": "object", "properties": {}}
    },
    handler=_ab_get_title,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_get_url",
    description="获取当前页面 URL。",
    schema={
        "name": "ab_get_url",
        "description": "获取当前 URL。",
        "parameters": {"type": "object", "properties": {}}
    },
    handler=_ab_get_url,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_eval",
    description="在当前页面执行 JavaScript 代码。",
    schema={
        "name": "ab_eval",
        "description": "执行 JavaScript。",
        "parameters": {
            "type": "object",
            "properties": {
                "js": {"type": "string", "description": "要执行的 JavaScript 代码"}
            },
            "required": ["js"]
        }
    },
    handler=_ab_eval,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="medium",
)

registry.register(
    name="ab_wait",
    description="等待页面元素出现、文本出现或 URL 变化。用于等待动态加载内容。",
    schema={
        "name": "ab_wait",
        "description": "等待条件满足。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "等待元素出现的选择器"},
                "text": {"type": "string", "description": "等待页面出现的文本"},
                "timeout_ms": {"type": "integer", "description": "超时毫秒数", "default": 10000}
            }
        }
    },
    handler=_ab_wait,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_find",
    description="智能查找元素并操作。支持按 role/text/label/placeholder 等查找。比 CSS 选择器更语义化。",
    schema={
        "name": "ab_find",
        "description": "智能查找元素并操作。",
        "parameters": {
            "type": "object",
            "properties": {
                "by": {"type": "string", "description": "查找方式: role/text/label/placeholder/alt/title/testid/first/last/nth"},
                "value": {"type": "string", "description": "查找值（如 button/Submit/Email）"},
                "action": {"type": "string", "description": "操作: click/fill/type/hover/focus/check/uncheck/text", "default": "click"}
            },
            "required": ["by", "value"]
        }
    },
    handler=_ab_find,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_scroll",
    description="滚动页面。方向: up/down/left/right。",
    schema={
        "name": "ab_scroll",
        "description": "滚动页面。",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "方向: up/down/left/right"},
                "pixels": {"type": "integer", "description": "滚动像素数", "default": 300}
            },
            "required": ["direction"]
        }
    },
    handler=_ab_scroll,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_hover",
    description="悬停在元素上（触发 hover 效果）。",
    schema={
        "name": "ab_hover",
        "description": "悬停元素。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "元素选择器"}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_hover,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_select",
    description="选择下拉框选项。",
    schema={
        "name": "ab_select",
        "description": "选择下拉框选项。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "下拉框选择器"},
                "value": {"type": "string", "description": "选项值"}
            },
            "required": ["selector", "value"]
        }
    },
    handler=_ab_select,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_is_visible",
    description="检查元素是否在页面上可见。",
    schema={
        "name": "ab_is_visible",
        "description": "检查元素是否可见。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "元素选择器"}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_is_visible,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_dblclick",
    description="双击元素。",
    schema={
        "name": "ab_dblclick",
        "description": "双击元素。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "元素选择器"}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_dblclick,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_check",
    description="勾选复选框。",
    schema={
        "name": "ab_check",
        "description": "勾选复选框。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "复选框选择器"}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_check,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_uncheck",
    description="取消勾选复选框。",
    schema={
        "name": "ab_uncheck",
        "description": "取消勾选复选框。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "复选框选择器"}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_uncheck,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_scrollintoview",
    description="滚动指定元素到可视区域。",
    schema={
        "name": "ab_scrollintoview",
        "description": "滚动元素到可视区域。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "元素选择器"}
            },
            "required": ["selector"]
        }
    },
    handler=_ab_scrollintoview,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_drag",
    description="拖拽元素到目标位置。",
    schema={
        "name": "ab_drag",
        "description": "拖拽元素。",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源元素选择器"},
                "target": {"type": "string", "description": "目标元素选择器"}
            },
            "required": ["source", "target"]
        }
    },
    handler=_ab_drag,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_pdf",
    description="将当前页面保存为 PDF 文件。",
    schema={
        "name": "ab_pdf",
        "description": "保存页面为 PDF。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "PDF 保存路径"}
            },
            "required": ["path"]
        }
    },
    handler=_ab_pdf,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_connect",
    description="通过 CDP 协议连接已运行的浏览器实例（如 Chrome DevTools）。",
    schema={
        "name": "ab_connect",
        "description": "连接已有浏览器。",
        "parameters": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "CDP 端口", "default": 9222}
            }
        }
    },
    handler=_ab_connect,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)

registry.register(
    name="ab_close",
    description="关闭 agent-browser 浏览器实例。",
    schema={
        "name": "ab_close",
        "description": "关闭浏览器。",
        "parameters": {"type": "object", "properties": {}}
    },
    handler=_ab_close,
    category="browser",
    check_fn=_check_agent_browser,
    risk_level="low",
)
