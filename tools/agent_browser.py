"""
Playwright 浏览器自动化模块（替代 agent-browser CLI）

使用 Playwright Python API 直接控制浏览器，消除 subprocess/CDP 端口管理的复杂性。
保持与原 agent_browser.py 完全相同的公开 API，上层代码零改动。

安装：
    pip install playwright
    playwright install chromium
"""
import asyncio
import base64
import json
import os
import sys
import tempfile
import threading
import time
from typing import Optional


# ═══ 全局状态 ═══

_pw = None           # Playwright 实例
_browser = None      # Browser 实例
_page = None         # 当前活跃 Page
_loop = None         # 专用事件循环
_loop_thread = None  # 事件循环线程
_initialized = False # 是否已初始化
_element_counter = 0 # 元素计数器（用于 snapshot 的 @ref 映射）
_ref_map = {}        # @ref → selector 映射

DEFAULT_TIMEOUT = 30000  # 毫秒
MAX_OUTPUT = 8000


# ═══ 事件循环管理 ═══

def _get_loop() -> asyncio.AbstractEventLoop:
    """获取专用事件循环（在后台线程运行）"""
    global _loop, _loop_thread
    if _loop is None or (_loop_thread and not _loop_thread.is_alive()):
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
        _loop_thread.start()
    return _loop


def _run_async(coro):
    """在线程安全的事件循环中执行异步代码"""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=60)
    except Exception as e:
        raise e


# ═══ 浏览器生命周期 ═══

async def _ensure_browser():
    """确保浏览器和页面已就绪（快速失败：Chromium 不存在时 1 秒内返回错误）"""
    global _pw, _browser, _page, _initialized

    if _page and not _page.is_closed():
        return

    # 快速预检：Chromium 是否存在（避免 launch 挂住几十秒）
    if not is_available():
        raise RuntimeError(
            "Chromium 浏览器未安装。请先运行: pip install playwright && playwright install chromium"
        )

    if _pw is None:
        from playwright.async_api import async_playwright
        _pw = await asyncio.wait_for(async_playwright().start(), timeout=10)

    if _browser is None or not _browser.is_connected():
        _browser = await asyncio.wait_for(
            _pw.chromium.launch(
                headless=False,
                args=[
                    "--no-first-run",
                    "--disable-blink-features=AutomationControlled",
                ]
            ),
            timeout=15  # 最多等 15 秒，超时直接报错
        )

    if _page is None or _page.is_closed():
        _page = await _browser.new_page()
        _page.set_default_timeout(DEFAULT_TIMEOUT)

    _initialized = True


def is_available() -> bool:
    """检查 Playwright 是否可用"""
    try:
        import playwright
        return True
    except ImportError:
        return False


# ═══ 结果封装 ═══

async def _page_info() -> dict:
    """获取当前页面的轻量信息（url + title + 前500字文本）"""
    global _page
    if not _page or _page.is_closed():
        return {}
    try:
        url = _page.url
        title = await _page.title()
        try:
            text = await _page.inner_text("body")
            page_text = text[:500] if text else ""
        except Exception:
            page_text = ""
        return {"url": url, "title": title, "page_text": page_text}
    except Exception:
        return {}


def _ok(output: str, **extra) -> dict:
    result = {"success": True, "output": output[:MAX_OUTPUT]}
    result.update(extra)
    return result


async def _ok_with_page(output: str, **extra) -> dict:
    """成功返回 + 自动附带页面信息"""
    result = {"success": True, "output": output[:MAX_OUTPUT]}
    info = await _page_info()
    result.update(info)
    result.update(extra)
    return result


def _err(error: str, **extra) -> dict:
    result = {"success": False, "error": error, "_tool_failed": True}
    result.update(extra)
    return result


# ═══ 选择器解析 ═══

def _resolve_selector(selector: str) -> str:
    """解析选择器，支持 @ref 映射"""
    if selector.startswith("@e"):
        ref = selector[1:]  # 去掉 @
        if ref in _ref_map:
            return _ref_map[ref]
    return selector


# ═══ Accessibility Snapshot（核心能力）═══

async def _build_snapshot(page) -> str:
    """构建带 @ref 的可访问性树快照

    使用 Playwright 的 aria snapshot，输出格式类似 agent-browser：
    @e1 [button] "搜索"
    @e2 [textbox] "请输入关键词"
    """
    global _element_counter, _ref_map
    _element_counter = 0
    _ref_map = {}

    try:
        # 用 JS 构建精简的可访问性树
        tree = await page.evaluate("""() => {
            function isVisible(el) {
                const style = window.getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
            }

            function getRole(el) {
                const role = el.getAttribute('role');
                if (role) return role;
                const tag = el.tagName.toLowerCase();
                const map = {
                    'a': 'link', 'button': 'button', 'input': 'textbox',
                    'select': 'combobox', 'textarea': 'textbox', 'img': 'img',
                    'h1': 'heading', 'h2': 'heading', 'h3': 'heading',
                    'h4': 'heading', 'h5': 'heading', 'h6': 'heading',
                    'nav': 'navigation', 'main': 'main', 'header': 'banner',
                    'footer': 'contentinfo', 'form': 'form', 'table': 'table',
                    'ul': 'list', 'ol': 'list', 'li': 'listitem',
                    'label': 'label', 'p': 'paragraph', 'span': 'text',
                    'div': 'group', 'section': 'region', 'article': 'article',
                };
                return map[tag] || null;
            }

            function getName(el) {
                const ariaLabel = el.getAttribute('aria-label');
                if (ariaLabel) return ariaLabel;
                const title = el.getAttribute('title');
                if (title) return title;
                const placeholder = el.getAttribute('placeholder');
                if (placeholder) return placeholder;
                const alt = el.getAttribute('alt');
                if (alt) return alt;
                const text = el.textContent?.trim().substring(0, 80);
                if (text) return text;
                return '';
            }

            const interactive = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="textbox"], [role="checkbox"], [role="radio"], [role="tab"], [role="menuitem"]';
            const elements = document.querySelectorAll(interactive);
            const result = [];

            for (const el of elements) {
                if (!isVisible(el)) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;

                const role = getRole(el);
                const name = getName(el);
                const tag = el.tagName.toLowerCase();
                const type = el.getAttribute('type') || '';
                const href = el.getAttribute('href') || '';
                const value = el.value || '';

                // 生成唯一选择器
                let selector = '';
                if (el.id) {
                    selector = '#' + CSS.escape(el.id);
                } else if (el.name) {
                    selector = tag + '[name="' + el.name + '"]';
                } else {
                    // 用 nth-of-type
                    const parent = el.parentElement;
                    if (parent) {
                        const siblings = parent.querySelectorAll(tag);
                        const idx = Array.from(siblings).indexOf(el);
                        selector = tag + ':nth-of-type(' + (idx + 1) + ')';
                    } else {
                        selector = tag;
                    }
                }

                result.push({
                    role: role || tag,
                    name: name,
                    selector: selector,
                    tag: tag,
                    type: type,
                    href: href.substring(0, 100),
                    value: value.substring(0, 100),
                    rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) }
                });
            }
            return result;
        }""")

        # 格式化输出
        lines = []
        for i, el in enumerate(tree, 1):
            ref = f"@e{i}"
            _ref_map[ref] = el.get("selector", "")

            role = el.get("role", "?")
            name = el.get("name", "")
            tag = el.get("tag", "")
            extra = []

            if el.get("type"):
                extra.append(f"type={el['type']}")
            if el.get("href"):
                extra.append(f"href={el['href']}")
            if el.get("value"):
                extra.append(f"value=\"{el['value']}\"")

            extra_str = f" ({', '.join(extra)})" if extra else ""
            name_str = f' "{name}"' if name else ""
            lines.append(f"  {ref} [{role}]{name_str}{extra_str}")

        _element_counter = len(lines)
        title = await page.title()
        url = page.url

        header = f"📄 {title}\n🔗 {url}\n---"
        if lines:
            body = "\n".join(lines)
        else:
            body = "(页面无可交互元素)"

        return f"{header}\n{body}\n---\n共 {_element_counter} 个可交互元素"

    except Exception as e:
        return f"Snapshot 失败: {str(e)}"


# ═══ 核心命令封装（公开 API）═══

def ab_open(url: str) -> dict:
    """打开网页"""
    async def _open():
        await _ensure_browser()
        try:
            await _page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
            # 等待页面基本渲染完成（不等网络空闲，避免慢页面超时）
            try:
                await _page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass  # 超时不阻塞，继续返回
            title = await _page.title()
            return await _ok_with_page(f"已打开: {title}\n{_page.url}")
        except Exception as e:
            return _err(f"打开失败: {str(e)}")

    try:
        return _run_async(_open())
    except Exception as e:
        return _err(f"打开失败: {str(e)}")


def ab_close() -> dict:
    """关闭浏览器"""
    async def _close():
        global _page, _browser, _pw
        if _page and not _page.is_closed():
            await _page.close()
            _page = None
        if _browser:
            await _browser.close()
            _browser = None
        if _pw:
            await _pw.stop()
            _pw = None
        return _ok("浏览器已关闭")

    try:
        return _run_async(_close())
    except Exception as e:
        return _err(f"关闭失败: {str(e)}")


def ab_snapshot(interactive: bool = False, full: bool = False) -> dict:
    """获取页面快照

    默认返回轻量 page_text（前500字），适合 LLM 判断页面内容。
    full=True 时返回完整可访问性树（用于需要精确操作元素的场景）。
    """
    async def _snapshot():
        await _ensure_browser()
        try:
            if full:
                # 完整可访问性树（用于 ab_click 等需要 @ref 的场景）
                snapshot_text = await _build_snapshot(_page)
                return await _ok_with_page(snapshot_text)
            else:
                # 轻量模式：只返回 url + title + page_text
                return await _ok_with_page("快照已获取（轻量模式）")
        except Exception as e:
            return _err(f"快照失败: {str(e)}")

    try:
        return _run_async(_snapshot())
    except Exception as e:
        return _err(f"快照失败: {str(e)}")


def ab_click(selector: str, new_tab: bool = False) -> dict:
    """点击元素"""
    async def _click():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            await _page.locator(resolved).click(timeout=10000)
            # 等待点击后的页面变化
            try:
                await _page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            return await _ok_with_page(f"已点击: {selector}")
        except Exception as e:
            return _err(f"点击失败: {str(e)}")

    try:
        return _run_async(_click())
    except Exception as e:
        return _err(f"点击失败: {str(e)}")


def ab_dblclick(selector: str) -> dict:
    """双击元素"""
    async def _dblclick():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            await _page.locator(resolved).dblclick(timeout=10000)
            return await _ok_with_page(f"已双击: {selector}")
        except Exception as e:
            return _err(f"双击失败: {str(e)}")

    try:
        return _run_async(_dblclick())
    except Exception as e:
        return _err(f"双击失败: {str(e)}")


def ab_fill(selector: str, text: str) -> dict:
    """清空并填写文本"""
    async def _fill():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            await _page.locator(resolved).fill(text, timeout=10000)
            return await _ok_with_page(f"已填写: {text[:50]}")
        except Exception as e:
            return _err(f"填写失败: {str(e)}")

    try:
        return _run_async(_fill())
    except Exception as e:
        return _err(f"填写失败: {str(e)}")


def ab_type(selector: str, text: str) -> dict:
    """逐字输入文本"""
    async def _type():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            await _page.locator(resolved).press_sequentially(text, delay=50, timeout=10000)
            return await _ok_with_page(f"已输入: {text[:50]}")
        except Exception as e:
            return _err(f"输入失败: {str(e)}")

    try:
        return _run_async(_type())
    except Exception as e:
        return _err(f"输入失败: {str(e)}")


def ab_press(key: str) -> dict:
    """按下键盘按键"""
    async def _press():
        await _ensure_browser()
        try:
            await _page.keyboard.press(key)
            return await _ok_with_page(f"已按下: {key}")
        except Exception as e:
            return _err(f"按键失败: {str(e)}")

    try:
        return _run_async(_press())
    except Exception as e:
        return _err(f"按键失败: {str(e)}")


def ab_hover(selector: str) -> dict:
    """悬停元素"""
    async def _hover():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            await _page.locator(resolved).hover(timeout=10000)
            return await _ok_with_page(f"已悬停: {selector}")
        except Exception as e:
            return _err(f"悬停失败: {str(e)}")

    try:
        return _run_async(_hover())
    except Exception as e:
        return _err(f"悬停失败: {str(e)}")


def ab_select(selector: str, value: str) -> dict:
    """选择下拉框选项"""
    async def _select():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            await _page.locator(resolved).select_option(value, timeout=10000)
            return await _ok_with_page(f"已选择: {value}")
        except Exception as e:
            return _err(f"选择失败: {str(e)}")

    try:
        return _run_async(_select())
    except Exception as e:
        return _err(f"选择失败: {str(e)}")


def ab_check(selector: str) -> dict:
    """勾选复选框"""
    async def _check():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            await _page.locator(resolved).check(timeout=10000)
            return await _ok_with_page(f"已勾选: {selector}")
        except Exception as e:
            return _err(f"勾选失败: {str(e)}")

    try:
        return _run_async(_check())
    except Exception as e:
        return _err(f"勾选失败: {str(e)}")


def ab_uncheck(selector: str) -> dict:
    """取消勾选复选框"""
    async def _uncheck():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            await _page.locator(resolved).uncheck(timeout=10000)
            return await _ok_with_page(f"已取消勾选: {selector}")
        except Exception as e:
            return _err(f"取消勾选失败: {str(e)}")

    try:
        return _run_async(_uncheck())
    except Exception as e:
        return _err(f"取消勾选失败: {str(e)}")


def ab_scroll(direction: str, pixels: int = 300, selector: str = None) -> dict:
    """滚动页面"""
    async def _scroll():
        await _ensure_browser()
        try:
            dx, dy = 0, 0
            if direction == "down":
                dy = pixels
            elif direction == "up":
                dy = -pixels
            elif direction == "right":
                dx = pixels
            elif direction == "left":
                dx = -pixels

            if selector:
                resolved = _resolve_selector(selector)
                await _page.locator(resolved).scroll_into_view_if_needed()
            else:
                await _page.mouse.wheel(dx, dy)

            return _ok(f"已滚动 {direction} {pixels}px")
        except Exception as e:
            return _err(f"滚动失败: {str(e)}")

    try:
        return _run_async(_scroll())
    except Exception as e:
        return _err(f"滚动失败: {str(e)}")


def ab_scrollintoview(selector: str) -> dict:
    """滚动元素到可视区域"""
    async def _scroll_into_view():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            await _page.locator(resolved).scroll_into_view_if_needed(timeout=10000)
            return _ok(f"已滚动到: {selector}")
        except Exception as e:
            return _err(f"滚动失败: {str(e)}")

    try:
        return _run_async(_scroll_into_view())
    except Exception as e:
        return _err(f"滚动失败: {str(e)}")


def ab_drag(source: str, target: str) -> dict:
    """拖拽"""
    async def _drag():
        await _ensure_browser()
        src = _resolve_selector(source)
        tgt = _resolve_selector(target)
        try:
            await _page.locator(src).drag_to(_page.locator(tgt), timeout=10000)
            return _ok(f"已拖拽: {source} → {target}")
        except Exception as e:
            return _err(f"拖拽失败: {str(e)}")

    try:
        return _run_async(_drag())
    except Exception as e:
        return _err(f"拖拽失败: {str(e)}")


def ab_screenshot(path: str = None, full_page: bool = False, annotate: bool = False) -> dict:
    """截图"""
    async def _screenshot():
        await _ensure_browser()
        try:
            if not path:
                fd, screenshot_path = tempfile.mkstemp(suffix=".png", prefix="yi-agent-")
                os.close(fd)
            else:
                screenshot_path = path

            await _page.screenshot(path=screenshot_path, full_page=full_page)

            with open(screenshot_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            return _ok(
                f"截图已保存: {screenshot_path}",
                base64=b64,
                path=screenshot_path,
            )
        except Exception as e:
            return _err(f"截图失败: {str(e)}")

    try:
        return _run_async(_screenshot())
    except Exception as e:
        return _err(f"截图失败: {str(e)}")


def ab_pdf(path: str) -> dict:
    """保存页面为 PDF"""
    async def _pdf():
        await _ensure_browser()
        try:
            await _page.pdf(path=path)
            return _ok(f"PDF 已保存: {path}")
        except Exception as e:
            return _err(f"PDF 失败: {str(e)}")

    try:
        return _run_async(_pdf())
    except Exception as e:
        return _err(f"PDF 失败: {str(e)}")


def ab_get_text(selector: str) -> dict:
    """获取元素文本"""
    async def _get_text():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            text = await _page.locator(resolved).text_content(timeout=10000)
            return _ok(text or "")
        except Exception as e:
            return _err(f"获取文本失败: {str(e)}")

    try:
        return _run_async(_get_text())
    except Exception as e:
        return _err(f"获取文本失败: {str(e)}")


def ab_get_html(selector: str) -> dict:
    """获取元素 innerHTML"""
    async def _get_html():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            html = await _page.locator(resolved).inner_html(timeout=10000)
            return _ok(html[:MAX_OUTPUT])
        except Exception as e:
            return _err(f"获取 HTML 失败: {str(e)}")

    try:
        return _run_async(_get_html())
    except Exception as e:
        return _err(f"获取 HTML 失败: {str(e)}")


def ab_get_value(selector: str) -> dict:
    """获取输入框值"""
    async def _get_value():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            value = await _page.locator(resolved).input_value(timeout=10000)
            return _ok(value)
        except Exception as e:
            return _err(f"获取值失败: {str(e)}")

    try:
        return _run_async(_get_value())
    except Exception as e:
        return _err(f"获取值失败: {str(e)}")


def ab_get_attr(selector: str, attr: str) -> dict:
    """获取元素属性"""
    async def _get_attr():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            value = await _page.locator(resolved).get_attribute(attr, timeout=10000)
            return _ok(value or "")
        except Exception as e:
            return _err(f"获取属性失败: {str(e)}")

    try:
        return _run_async(_get_attr())
    except Exception as e:
        return _err(f"获取属性失败: {str(e)}")


def ab_get_title() -> dict:
    """获取页面标题"""
    async def _get_title():
        await _ensure_browser()
        try:
            title = await _page.title()
            return _ok(title)
        except Exception as e:
            return _err(f"获取标题失败: {str(e)}")

    try:
        return _run_async(_get_title())
    except Exception as e:
        return _err(f"获取标题失败: {str(e)}")


def ab_get_url() -> dict:
    """获取当前 URL"""
    async def _get_url():
        await _ensure_browser()
        try:
            return _ok(_page.url)
        except Exception as e:
            return _err(f"获取 URL 失败: {str(e)}")

    try:
        return _run_async(_get_url())
    except Exception as e:
        return _err(f"获取 URL 失败: {str(e)}")


def ab_eval(js: str) -> dict:
    """执行 JavaScript"""
    async def _eval():
        await _ensure_browser()
        try:
            result = await _page.evaluate(js)
            output = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
            return _ok(output[:MAX_OUTPUT])
        except Exception as e:
            return _err(f"JS 执行失败: {str(e)}")

    try:
        return _run_async(_eval())
    except Exception as e:
        return _err(f"JS 执行失败: {str(e)}")


def ab_wait(selector: str = None, text: str = None, url: str = None,
            timeout_ms: int = 10000, load_state: str = None, js_fn: str = None) -> dict:
    """等待条件满足"""
    async def _wait():
        await _ensure_browser()
        try:
            if load_state:
                await _page.wait_for_load_state(load_state, timeout=timeout_ms)
                return _ok(f"加载状态: {load_state}")

            if selector:
                resolved = _resolve_selector(selector)
                await _page.locator(resolved).wait_for(state="visible", timeout=timeout_ms)
                return _ok(f"元素已出现: {selector}")

            if text:
                await _page.wait_for_function(
                    f'document.body.textContent.includes("{text}")',
                    timeout=timeout_ms
                )
                return _ok(f"文本已出现: {text}")

            if url:
                await _page.wait_for_url(f"**{url}**", timeout=timeout_ms)
                return _ok(f"URL 匹配: {url}")

            if js_fn:
                await _page.wait_for_function(js_fn, timeout=timeout_ms)
                return _ok("JS 条件满足")

            return _err("请指定等待条件（selector/text/url/load_state/js_fn）")
        except Exception as e:
            return _err(f"等待超时: {str(e)}")

    try:
        return _run_async(_wait())
    except Exception as e:
        return _err(f"等待失败: {str(e)}")


def ab_find(by: str, value: str, action: str = "click", name: str = None) -> dict:
    """智能查找并操作元素"""
    async def _find():
        await _ensure_browser()
        try:
            locator = None
            if by == "role":
                locator = _page.get_by_role(value, name=name)
            elif by == "text":
                locator = _page.get_by_text(value, exact=True)
            elif by == "label":
                locator = _page.get_by_label(value)
            elif by == "placeholder":
                locator = _page.get_by_placeholder(value)
            elif by == "alt":
                locator = _page.get_by_alt_text(value)
            elif by == "title":
                locator = _page.get_by_title(value)
            elif by == "testid":
                locator = _page.get_by_test_id(value)
            else:
                return _err(f"不支持的查找方式: {by}")

            if action == "click":
                await locator.click(timeout=10000)
                return _ok(f"已点击 {by}={value}")
            elif action == "fill":
                await locator.fill(name or value, timeout=10000)
                return _ok(f"已填写 {by}={value}")
            elif action == "type":
                await locator.press_sequentially(name or value, delay=50, timeout=10000)
                return _ok(f"已输入 {by}={value}")
            elif action == "hover":
                await locator.hover(timeout=10000)
                return _ok(f"已悬停 {by}={value}")
            elif action == "focus":
                await locator.focus(timeout=10000)
                return _ok(f"已聚焦 {by}={value}")
            elif action == "check":
                await locator.check(timeout=10000)
                return _ok(f"已勾选 {by}={value}")
            elif action == "uncheck":
                await locator.uncheck(timeout=10000)
                return _ok(f"已取消勾选 {by}={value}")
            elif action == "text":
                text = await locator.text_content(timeout=10000)
                return _ok(text or "")
            else:
                return _err(f"不支持的操作: {action}")
        except Exception as e:
            return _err(f"查找/操作失败: {str(e)}")

    try:
        return _run_async(_find())
    except Exception as e:
        return _err(f"查找失败: {str(e)}")


def ab_is_visible(selector: str) -> dict:
    """检查元素是否可见"""
    async def _is_visible():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            visible = await _page.locator(resolved).is_visible()
            return _ok(str(visible).lower())
        except Exception as e:
            return _err(f"检查失败: {str(e)}")

    try:
        return _run_async(_is_visible())
    except Exception as e:
        return _err(f"检查失败: {str(e)}")


def ab_is_enabled(selector: str) -> dict:
    """检查元素是否可用"""
    async def _is_enabled():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            enabled = await _page.locator(resolved).is_enabled()
            return _ok(str(enabled).lower())
        except Exception as e:
            return _err(f"检查失败: {str(e)}")

    try:
        return _run_async(_is_enabled())
    except Exception as e:
        return _err(f"检查失败: {str(e)}")


def ab_get_count(selector: str) -> dict:
    """统计匹配元素数量"""
    async def _get_count():
        await _ensure_browser()
        resolved = _resolve_selector(selector)
        try:
            count = await _page.locator(resolved).count()
            return _ok(str(count))
        except Exception as e:
            return _err(f"统计失败: {str(e)}")

    try:
        return _run_async(_get_count())
    except Exception as e:
        return _err(f"统计失败: {str(e)}")


def ab_connect(port: int = 9222) -> dict:
    """连接已有浏览器（兼容接口，Playwright 不需要这个）"""
    return _ok("Playwright 模式下不需要手动连接浏览器")


def ab_close_all() -> dict:
    """关闭所有"""
    return ab_close()


def ab_upgrade() -> dict:
    """升级（Playwright 通过 pip 升级）"""
    return _ok("请运行: pip install --upgrade playwright && playwright install chromium")


def ab_install(with_deps: bool = False) -> dict:
    """安装浏览器"""
    async def _install():
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "playwright", "install", "chromium",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return _ok(f"Chromium 安装完成\n{stdout.decode()[-500:]}")
            else:
                return _err(f"安装失败: {stderr.decode()[-500:]}")
        except Exception as e:
            return _err(f"安装失败: {str(e)}")

    try:
        return _run_async(_install())
    except Exception as e:
        return _err(f"安装失败: {str(e)}")


# ═══ 高级组合操作 ═══

def ab_navigate_and_snapshot(url: str) -> dict:
    """打开网页并获取快照"""
    open_result = ab_open(url)
    if not open_result.get("success"):
        return open_result
    return ab_snapshot()


def ab_search_and_click(url: str, search_text: str, input_selector: str = None,
                         submit_selector: str = None) -> dict:
    """打开网页 → 输入搜索文本 → 提交"""
    open_result = ab_open(url)
    if not open_result.get("success"):
        return open_result

    if not input_selector:
        snap = ab_snapshot()
        if not snap.get("success"):
            return snap
        for sel in ['input[type="search"]', 'input[name="q"]', 'input[placeholder*="搜索"]',
                     'input[placeholder*="search"]', '#search', '.search-input']:
            vis = ab_is_visible(sel)
            if vis.get("success") and "true" in vis.get("output", "").lower():
                input_selector = sel
                break
        if not input_selector:
            return _err("未找到搜索框，请指定 input_selector")

    fill_result = ab_fill(input_selector, search_text)
    if not fill_result.get("success"):
        return fill_result

    if submit_selector:
        ab_click(submit_selector)
    else:
        ab_press("Enter")

    ab_wait(load_state="networkidle", timeout_ms=10000)
    return ab_snapshot()
