"""
YI-Agent — 轻量 Web 服务
为 index.html 提供 API 接口
"""
import os
import sys
import json
import time
import queue
import asyncio
import datetime
import threading
import logging
from pathlib import Path

# ═══ 确保子进程继承 venv 环境 ═══
# 如果 server.py 被 venv Python 启动，设置 PATH 让子进程的 pip/python 也指向 venv
_venv = os.environ.get("VIRTUAL_ENV", "")
if not _venv and hasattr(sys, 'prefix') and sys.prefix != sys.base_prefix:
    # 检测到在 venv 中运行但环境变量未设置（直接 python server.py 的情况）
    _venv = sys.prefix
if _venv:
    if sys.platform == "win32":
        _venv_bin = os.path.join(_venv, "Scripts")
    else:
        _venv_bin = os.path.join(_venv, "bin")
    if _venv_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _venv_bin + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("VIRTUAL_ENV", _venv)

# 配置日志（抓 500 根因）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('yi-agent')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify, send_from_directory, Response
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')

# ═══ 延迟初始化 Agent ═══
_agent_initialized = False
_registry = None
_skills = []

# ═══ 会话管理（修复：复用 Conversation，避免内存泄漏）═══
_sessions = {}  # session_id → Conversation
_session_locks = {}  # session_id → threading.Lock
_session_last_active = {}  # session_id → timestamp
_SESSION_TTL = 3600  # 会话过期时间（秒）
_loop = None     # 全局事件循环（修复：asyncio.run 嵌套问题）
_loop_thread = None


def _get_session_lock(session_id):
    """获取会话级锁（防并发写同一会话）"""
    if session_id not in _session_locks:
        _session_locks[session_id] = threading.Lock()
    return _session_locks[session_id]


def _cleanup_expired_sessions():
    """清理过期会话"""
    import time
    now = time.time()
    expired = [sid for sid, ts in _session_last_active.items() if now - ts > _SESSION_TTL]
    for sid in expired:
        _sessions.pop(sid, None)
        _session_locks.pop(sid, None)
        _session_last_active.pop(sid, None)
        logger.info(f"会话已过期清理: {sid}")

def _get_loop():
    """获取全局事件循环（在专用线程中运行）"""
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
        return future.result(timeout=180)
    except Exception as e:
        logger.error(f"_run_async 执行失败: {e}", exc_info=True)
        raise

def init_agent():
    global _agent_initialized, _registry, _skills
    if _agent_initialized:
        return
    import config
    from tools.registry import registry, discover_tools
    discover_tools()
    from skills.loader import load_all_skills
    _registry = registry
    _skills = load_all_skills()
    _agent_initialized = True


# ═══ 页面路由 ═══

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


# ═══ API 路由 ═══

@app.route('/api/status')
def api_status():
    """获取 Agent 状态"""
    init_agent()
    from manage.tool_manager import ToolManager
    from manage.skill_manager import SkillManager
    from manage.memory_manager import MemoryManager

    tool_mgr = ToolManager(_registry)
    skill_mgr = SkillManager()
    mem_mgr = MemoryManager()

    tools_data = tool_mgr.list_by_category()
    skills_data = skill_mgr.list_skills()
    mem_stats = mem_mgr.get_stats()

    return jsonify({
        'status': 'ok',
        'tools': tools_data.get('categories', {}),
        'tool_stats': tool_mgr.get_stats(),
        'skills': skills_data.get('skills', []),
        'memory_stats': mem_stats,
    })


@app.route('/api/chat', methods=['POST'])
def api_chat():
    """对话接口（修复：复用会话 + 统一事件循环 + 会话锁 + 权限集成）"""
    init_agent()
    data = request.get_json(force=True)
    message = data.get('message', '').strip()
    session_id = data.get('session_id', 'web-default')

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    # 清理过期会话
    _cleanup_expired_sessions()

    import config
    from core.conversation import Conversation

    # 会话级锁：同一会话串行处理
    lock = _get_session_lock(session_id)
    if not lock.acquire(blocking=False):
        return jsonify({
            'response': '⏳ 上一条消息还在处理中，请稍候...',
            'tool_calls': [], 'stats': {}, '_progress': [],
            '_busy': True,  # 前端识别：不是断线，是忙碌
        }), 429

    try:
        # 复用已有会话
        if session_id not in _sessions:
            _sessions[session_id] = Conversation(session_id=session_id, restore=True)
        conv = _sessions[session_id]

        import time
        _session_last_active[session_id] = time.time()

        # ── 权限集成：全局权限（后端持久化） + 前端请求权限（合并，以前端为主） ──
        # 全局权限来自 PUT /api/permissions 保存的配置，对所有会话生效
        global_bl = set(_global_permissions.get('toolBlacklist', []))
        global_sl = set(_global_permissions.get('skillBlacklist', []))
        global_risk = float(_global_permissions.get('riskTolerance', 1.0))

        # 前端请求中带的权限（单次请求级别，覆盖全局）
        permissions = data.get('permissions', {})
        if permissions:
            req_bl = set(permissions.get('toolBlacklist', []))
            req_sl = set(permissions.get('skillBlacklist', []))
            req_risk = float(permissions.get('riskTolerance', 1.0))
            # 合并：前端黑名单 ∪ 全局黑名单（取并集，更安全）
            conv._web_tool_blacklist = global_bl | req_bl
            conv._web_skill_blacklist = global_sl | req_sl
            # 风险容忍度：取更严格的那个
            conv._web_risk_tolerance = min(global_risk, req_risk)
        else:
            # 前端没带权限 → 用全局权限
            conv._web_tool_blacklist = global_bl
            conv._web_skill_blacklist = global_sl
            conv._web_risk_tolerance = global_risk

        progress_log = []

        def on_progress(msg):
            progress_log.append(msg)

        def on_confirm(cmd):
            # Web 模式：根据前端权限决定
            # riskTolerance=1.0（允许所有）→ 自动放行
            # riskTolerance<1.0 → 只拦截真正不可逆的破坏性操作
            risk_tol = getattr(conv, '_web_risk_tolerance', 1.0)
            if risk_tol >= 1.0:
                return True  # 前端开了允许所有，全部放行
            # 低风险容忍度：只拦真正的破坏性命令
            destructive = ['rm -rf', 'mkfs', 'dd if=', 'format', '> /dev/']
            cmd_lower = cmd.lower() if cmd else ''
            for pattern in destructive:
                if pattern in cmd_lower:
                    progress_log.append(f"⚠️ 破坏性操作已拦截: {cmd}")
                    return False
            return True

        # 修复：使用统一事件循环，避免 asyncio.run() 嵌套
        result = _run_async(conv.send(
            message,
            on_confirm=on_confirm,
            on_progress=on_progress,
        ))

        response = result.get('response', '(无回复)')
        tool_calls = result.get('tool_calls', [])
        stats = result.get('stats', {})

        # ── 持久化 token 统计 ──
        _persist_stats(session_id, stats)

        result_data = {
            'response': response,
            'reply': response,  # 兼容 channels/webchat.py 的字段名
            'tool_calls': tool_calls,
            'stats': stats,
            '_progress': progress_log,
        }

        return jsonify(result_data)

    except Exception as e:
        # 发生严重错误时移除该会话，下次重新创建
        _sessions.pop(session_id, None)
        logger.error(f"Chat API 错误: {e}", exc_info=True)
        return jsonify({
            'response': f'❌ Agent 执行出错: {str(e)}',
            'tool_calls': [],
            'stats': {},
        }), 500
    finally:
        lock.release()


# ── Token 统计持久化 ──
_STATS_FILE = os.path.join(os.path.dirname(__file__), 'data', 'session_stats.json')

def _persist_stats(session_id: str, stats: dict):
    """持久化 token 统计到文件"""
    try:
        os.makedirs(os.path.dirname(_STATS_FILE), exist_ok=True)
        all_stats = {}
        if os.path.isfile(_STATS_FILE):
            with open(_STATS_FILE, 'r', encoding='utf-8') as f:
                all_stats = json.load(f)

        prev = all_stats.get(session_id, {
            'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
            'tool_calls_count': 0, 'rounds': 0, 'estimated_cost_cny': 0,
            'updated_at': '',
        })
        prev['total_tokens'] += stats.get('total_tokens', 0)
        prev['prompt_tokens'] += stats.get('prompt_tokens', 0)
        prev['completion_tokens'] += stats.get('completion_tokens', 0)
        prev['tool_calls_count'] += stats.get('tool_calls_count', 0)
        prev['rounds'] += stats.get('rounds', 0)
        prev['estimated_cost_cny'] += stats.get('estimated_cost_cny', 0)
        prev['updated_at'] = datetime.datetime.now().isoformat()
        all_stats[session_id] = prev

        # 全局累计
        prev_global = all_stats.get('_global', {
            'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
            'tool_calls_count': 0, 'rounds': 0, 'estimated_cost_cny': 0,
        })
        prev_global['total_tokens'] += stats.get('total_tokens', 0)
        prev_global['prompt_tokens'] += stats.get('prompt_tokens', 0)
        prev_global['completion_tokens'] += stats.get('completion_tokens', 0)
        prev_global['tool_calls_count'] += stats.get('tool_calls_count', 0)
        prev_global['rounds'] += stats.get('rounds', 0)
        prev_global['estimated_cost_cny'] += stats.get('estimated_cost_cny', 0)
        all_stats['_global'] = prev_global

        with open(_STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@app.route('/api/stats')
def api_stats():
    """获取持久化的 token 统计"""
    try:
        session_id = request.args.get('session_id', '')
        if os.path.isfile(_STATS_FILE):
            with open(_STATS_FILE, 'r', encoding='utf-8') as f:
                all_stats = json.load(f)
            global_stats = all_stats.get('_global', {})
            session_stats = all_stats.get(session_id, {}) if session_id else {}
            return jsonify({
                'success': True,
                'global': global_stats,
                'session': session_stats,
            })
    except Exception:
        pass
    return jsonify({'success': True, 'global': {}, 'session': {}})


# ═══════════════════════════════════════════════════
# SSE 流式对话 — 实时推送思考过程
# ═══════════════════════════════════════════════════

class StreamBridge:
    """桥接异步 on_progress 回调与 SSE 流式输出（线程安全）"""
    def __init__(self):
        self.q = queue.Queue()
        self.tool_events = []
        self._done = False

    def on_progress(self, msg):
        self.q.put({"type": "progress", "msg": msg})

    def put_event(self, event):
        self.q.put(event)

    def mark_done(self):
        self._done = True
        self.q.put(None)

    def __iter__(self):
        while True:
            try:
                item = self.q.get(timeout=0.1)
            except queue.Empty:
                if self._done:
                    break
                continue
            if item is None:
                break
            yield item


def _describe_tool_args(func_name, args):
    """生成工具调用的可读参数描述"""
    if func_name in ("web_search", "ddg_search"):
        return f"搜索关键词：{args.get('query', '?')}"
    if func_name in ("ab_open",):
        return f"打开网址：{args.get('url', '?')[:60]}"
    if func_name in ("ab_click",):
        return f"点击元素：{args.get('selector', '?')[:40]}"
    if func_name in ("ab_fill", "ab_type"):
        return f"输入内容到：{args.get('selector', '?')[:30]}"
    if func_name in ("read_file",):
        return f"读取文件：{args.get('path', '?')}"
    if func_name in ("write_file",):
        content = args.get('content', '')
        return f"写入文件：{args.get('path', '?')}（{len(content)} 字符）"
    if func_name in ("edit_file",):
        return f"编辑文件：{args.get('path', '?')}"
    if func_name in ("run_command", "run_command_confirmed"):
        cmd = args.get('command', '?')
        return f"执行命令：{cmd[:60]}"
    if func_name in ("list_files", "scan_files", "find_files"):
        return f"扫描目录：{args.get('path', args.get('directory', '.'))}"
    if func_name in ("remember",):
        return f"记忆内容：{args.get('content', '?')[:40]}"
    if func_name in ("recall",):
        return f"回忆关键词：{args.get('query', '?')}"
    if func_name.startswith("git_"):
        return f"Git 操作：{args.get('message', args.get('branch', str(args)[:40]))}"
    if func_name in ("ab_screenshot",):
        return "截取当前页面截图"
    # 通用回退
    parts = [f"{k}={str(v)[:30]}" for k, v in list(args.items())[:3]]
    return "、".join(parts) if parts else "无参数"


def _describe_tool_result(func_name, result_raw, success):
    """生成工具执行结果的可读摘要"""
    if not success:
        try:
            data = json.loads(result_raw)
            err = data.get("error", data.get("reason", data.get("message", "")))
            return f"失败：{str(err)[:80]}"
        except Exception:
            return f"失败：{result_raw[:80]}"

    try:
        data = json.loads(result_raw)
    except Exception:
        return result_raw[:100] if result_raw else "完成"

    if func_name in ("web_search", "ddg_search"):
        results = data.get("results", [])
        titles = [r.get("title", "")[:30] for r in results[:3]]
        return f"找到 {len(results)} 条结果：{'、'.join(titles)}" if titles else "搜索完成"
    if func_name in ("read_file",):
        content = data.get("content", "")
        return f"读取 {len(content)} 字符：{content[:60].replace(chr(10), ' ')}..."
    if func_name in ("list_files", "scan_files", "find_files"):
        files = data.get("files", data.get("results", []))
        count = len(files) if isinstance(files, list) else 0
        return f"找到 {count} 个文件"
    if func_name in ("run_command", "run_command_confirmed"):
        output = data.get("output", data.get("stdout", ""))
        return f"执行完成：{output[:60].replace(chr(10), ' ')}..." if output else "执行完成（无输出）"
    if func_name in ("ab_screenshot",):
        return "截图已保存"
    if func_name in ("ab_open",):
        return f"已打开页面"
    if func_name in ("ab_get_text",):
        text = data.get("text", data.get("content", ""))
        return f"获取 {len(text)} 字符：{text[:60].replace(chr(10), ' ')}..."
    if func_name in ("remember",):
        return "已保存到记忆"
    if func_name in ("recall",):
        results = data.get("results", [])
        return f"找到 {len(results)} 条相关记忆"
    if func_name.startswith("git_"):
        return "Git 操作完成"
    # 通用
    if isinstance(data, dict):
        if data.get("success"):
            return "执行成功"
        keys = list(data.keys())[:3]
        return f"返回：{', '.join(keys)}"
    return "执行完成"


@app.route('/api/chat/stream', methods=['POST'])
def api_chat_stream():
    """SSE 流式对话 — 实时返回思考过程与工具调用"""
    init_agent()
    data = request.get_json(force=True)
    message = data.get('message', '').strip()
    session_id = data.get('session_id', 'web-default')

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    _cleanup_expired_sessions()
    import config
    from core.conversation import Conversation

    lock = _get_session_lock(session_id)
    if not lock.acquire(blocking=False):
        return jsonify({'error': '上一条消息还在处理中'}), 429

    try:
        if session_id not in _sessions:
            _sessions[session_id] = Conversation(session_id=session_id, restore=True)
        conv = _sessions[session_id]
        _session_last_active[session_id] = time.time()

        # ── 权限集成：全局权限 + 前端请求权限（合并） ──
        global_bl = set(_global_permissions.get('toolBlacklist', []))
        global_sl = set(_global_permissions.get('skillBlacklist', []))
        global_risk = float(_global_permissions.get('riskTolerance', 1.0))

        permissions = data.get('permissions', {})
        if permissions:
            req_bl = set(permissions.get('toolBlacklist', []))
            req_sl = set(permissions.get('skillBlacklist', []))
            req_risk = float(permissions.get('riskTolerance', 1.0))
            conv._web_tool_blacklist = global_bl | req_bl
            conv._web_skill_blacklist = global_sl | req_sl
            conv._web_risk_tolerance = min(global_risk, req_risk)
        else:
            conv._web_tool_blacklist = global_bl
            conv._web_skill_blacklist = global_sl
            conv._web_risk_tolerance = global_risk

        bridge = StreamBridge()

        # Monkey-patch _execute_tool 记录工具事件
        _orig_exec = conv._execute_tool

        async def _patched_exec(func_name, args, on_confirm=None):
            step_idx = len(bridge.tool_events)
            bridge.tool_events.append(func_name)
            # 生成可读的参数摘要
            args_desc = _describe_tool_args(func_name, args)
            bridge.put_event({
                "type": "tool_start", "step": step_idx,
                "tool": func_name, "args_preview": args_desc,
            })
            t0 = time.time()
            result = await _orig_exec(func_name, args, on_confirm=on_confirm)
            elapsed_ms = int((time.time() - t0) * 1000)
            try:
                success = "error" not in result.lower() and "blocked" not in result.lower()
            except Exception:
                success = True
            # 生成可读的结果摘要
            result_desc = _describe_tool_result(func_name, result, success)
            bridge.put_event({
                "type": "tool_result", "step": step_idx,
                "tool": func_name, "success": success, "elapsed_ms": elapsed_ms,
                "result_preview": result_desc,
            })
            return result

        conv._execute_tool = _patched_exec

        def _sse_on_confirm(cmd):
            risk_tol = getattr(conv, '_web_risk_tolerance', 1.0)
            if risk_tol >= 1.0:
                return True
            destructive = ['rm -rf', 'mkfs', 'dd if=', 'format', '> /dev/']
            cmd_lower = cmd.lower() if cmd else ''
            for pattern in destructive:
                if pattern in cmd_lower:
                    return False
            return True

        async def _run():
            try:
                result = await conv.send(
                    message,
                    on_confirm=_sse_on_confirm,
                    on_progress=bridge.on_progress,
                )
                bridge.put_event({"type": "response", "data": result})
            except Exception as e:
                bridge.put_event({"type": "error", "msg": str(e)})
            finally:
                conv._execute_tool = _orig_exec
                bridge.mark_done()
                lock.release()

        _run_async(_run())

        def generate():
            for evt in bridge:
                try:
                    yield f"event: {evt['type']}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                except Exception:
                    pass
            yield "event: done\ndata: {}\n\n"

        return Response(generate(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    except Exception as e:
        lock.release()
        logger.error(f"SSE 流式对话错误: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/chat/reset', methods=['POST'])
def api_chat_reset():
    """重置会话（修复：前端清空对话时同步清理后端会话）"""
    data = request.get_json(force=True)
    session_id = data.get('session_id', 'web-default')
    conv = _sessions.pop(session_id, None)
    _session_locks.pop(session_id, None)
    _session_last_active.pop(session_id, None)
    if conv:
        try:
            _run_async(conv.cleanup())
        except Exception:
            pass
        return jsonify({'success': True, 'message': f'会话 {session_id} 已删除'})
    return jsonify({'success': False, 'error': '会话不存在'}), 404


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.datetime.now().isoformat()})


@app.route('/api/heartbeat')
def api_heartbeat():
    """轻量心跳 — 前端保活检测用，不触发任何初始化"""
    return jsonify({'ok': True, 'ts': time.time()})


# ── 确认队列：Web 模式下的高风险操作确认 ──
_confirm_queue = {}  # session_id → {'cmd': str, 'event': threading.Event, 'approved': bool}

@app.route('/api/chat/confirm', methods=['POST'])
def api_chat_confirm():
    """Web 模式下的高风险操作确认"""
    data = request.get_json(force=True)
    session_id = data.get('session_id', 'web-default')
    approved = data.get('approved', False)

    entry = _confirm_queue.get(session_id)
    if entry:
        entry['approved'] = approved
        entry['event'].set()
        return jsonify({'success': True, 'approved': approved})
    return jsonify({'success': False, 'error': '没有待确认的操作'}), 404


@app.route('/api/settings', methods=['GET'])
def api_settings_get():
    """获取当前后端配置（不暴露完整 key）"""
    import config
    api_key = os.environ.get('LLM_API_KEY', '')
    base_url = os.environ.get('LLM_BASE_URL', '')
    model = os.environ.get('LLM_MODEL', 'deepseek-chat')
    return jsonify({
        'success': True,
        'settings': {
            'apiKey': api_key[:8] + '***' if len(api_key) > 8 else '',
            'apiKeySet': bool(api_key),
            'baseUrl': base_url,
            'model': model,
        }
    })


@app.route('/api/settings', methods=['PUT'])
def api_settings_update():
    """更新后端配置（写入 .env 文件）"""
    data = request.get_json(force=True)
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    try:
        # 读取现有 .env
        lines = []
        if os.path.isfile(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

        # 更新字段
        updates = {}
        if 'apiKey' in data and data['apiKey']:
            updates['LLM_API_KEY'] = data['apiKey']
        if 'baseUrl' in data:
            updates['LLM_BASE_URL'] = data['baseUrl']
        if 'model' in data:
            updates['LLM_MODEL'] = data['model']
        if 'allowedPaths' in data:
            updates['ALLOWED_PATHS'] = data['allowedPaths']

        # 写入 .env
        new_lines = []
        found_keys = set()
        for line in lines:
            key = line.split('=')[0].strip() if '=' in line else ''
            if key in updates:
                new_lines.append(f'{key}={updates[key]}\n')
                found_keys.add(key)
            else:
                new_lines.append(line)
        for key, val in updates.items():
            if key not in found_keys:
                new_lines.append(f'{key}={val}\n')

        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        # 更新环境变量（立即生效）
        for key, val in updates.items():
            os.environ[key] = val

        # 重新加载配置模块 + 重置 LLM 客户端（让新 key 立即生效）
        try:
            import config as _config
            _config.reload_config()
            import core.llm as _llm
            _llm.reset_client()
        except Exception as reload_err:
            logger.warning(f"配置热重载失败（重启后端可解决）: {reload_err}")

        return jsonify({'success': True, 'message': '配置已保存并立即生效'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
# 工具管理 API
# ═══════════════════════════════════════════════════

@app.route('/api/tools')
def api_tools_list():
    """列出所有工具（按分类分组）"""
    init_agent()
    from manage.tool_manager import ToolManager
    mgr = ToolManager(_registry)
    return jsonify(mgr.list_by_category())


@app.route('/api/tools/search')
def api_tools_search():
    """搜索工具"""
    keyword = request.args.get('q', '')
    init_agent()
    from manage.tool_manager import ToolManager
    mgr = ToolManager(_registry)
    return jsonify(mgr.search(keyword))


@app.route('/api/tools/<name>/toggle', methods=['POST'])
def api_tools_toggle(name):
    """启用/禁用工具"""
    init_agent()
    data = request.get_json(force=True)
    enabled = data.get('enabled', True)
    from manage.tool_manager import ToolManager
    mgr = ToolManager(_registry)
    return jsonify(mgr.toggle(name, enabled))


@app.route('/api/tools/auto-configure', methods=['POST'])
def api_tools_auto():
    """一键自动配置"""
    init_agent()
    from manage.tool_manager import ToolManager
    mgr = ToolManager(_registry)
    return jsonify(mgr.auto_configure())


# ═══════════════════════════════════════════════════
# 技能管理 API
# ═══════════════════════════════════════════════════

@app.route('/api/skills')
def api_skills_list():
    """列出所有技能"""
    from manage.skill_manager import SkillManager
    mgr = SkillManager()
    return jsonify(mgr.list_skills())


@app.route('/api/skills/<name>')
def api_skills_read(name):
    """读取技能内容"""
    from manage.skill_manager import SkillManager
    mgr = SkillManager()
    return jsonify(mgr.read_skill(name))


@app.route('/api/skills/<name>', methods=['PUT'])
def api_skills_update(name):
    """更新技能内容"""
    data = request.get_json(force=True)
    content = data.get('content', '')
    if not content:
        return jsonify({'success': False, 'error': '内容不能为空'}), 400
    from manage.skill_manager import SkillManager
    mgr = SkillManager()
    return jsonify(mgr.update_skill(name, content))


@app.route('/api/skills', methods=['POST'])
def api_skills_create():
    """创建新技能"""
    data = request.get_json(force=True)
    from manage.skill_manager import SkillManager
    mgr = SkillManager()
    return jsonify(mgr.create_skill(data.get('name', ''), data.get('description', '')))


@app.route('/api/skills/<name>', methods=['DELETE'])
def api_skills_delete(name):
    """删除技能"""
    from manage.skill_manager import SkillManager
    mgr = SkillManager()
    return jsonify(mgr.delete_skill(name, confirm=True))


@app.route('/api/skills/import', methods=['POST'])
def api_skills_import():
    """导入技能 — 支持上传 SKILL.md 文件或粘贴内容"""
    import config
    try:
        # 支持两种方式：文件上传 或 JSON 粘贴
        if request.content_type and 'multipart' in request.content_type:
            # 文件上传
            file = request.files.get('file')
            if not file:
                return jsonify({'success': False, 'error': '未找到文件'}), 400
            content = file.read().decode('utf-8')
            # 从文件名推断技能名
            filename = file.filename or 'imported-skill'
            skill_name = filename.replace('SKILL.md', '').replace('.md', '').strip('-_').lower()
            if not skill_name:
                skill_name = 'imported-skill'
        else:
            # JSON 方式
            data = request.get_json(force=True)
            content = data.get('content', '')
            skill_name = data.get('name', '')

        if not content or not content.strip():
            return jsonify({'success': False, 'error': '内容为空'}), 400

        # 从 YAML frontmatter 提取技能名
        import re
        fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if fm_match:
            try:
                import yaml
                fm = yaml.safe_load(fm_match.group(1)) or {}
                if fm.get('name') and not skill_name:
                    skill_name = fm['name']
            except Exception:
                pass

        if not skill_name:
            skill_name = 'imported-skill'

        # 校验技能名
        skill_name = re.sub(r'[^a-zA-Z0-9\-_]', '-', skill_name).strip('-').lower()
        if not skill_name:
            skill_name = 'imported-skill'

        # 保存到 skills 目录
        skills_dir = os.path.join(config.WORKSPACE, 'skills')
        os.makedirs(skills_dir, exist_ok=True)
        skill_dir = os.path.join(skills_dir, skill_name)
        os.makedirs(skill_dir, exist_ok=True)

        skill_path = os.path.join(skill_dir, 'SKILL.md')

        # 如果已存在，备份旧文件
        if os.path.exists(skill_path):
            import shutil
            from datetime import datetime
            backup = skill_path + f'.{datetime.now().strftime("%Y%m%d%H%M%S")}.bak'
            shutil.copy2(skill_path, backup)

        with open(skill_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # 清除技能缓存（强制重新加载）
        try:
            from skills import loader
            loader._skills_cache = None
        except Exception:
            pass

        logger.info(f"技能已导入: {skill_name}")
        return jsonify({
            'success': True,
            'name': skill_name,
            'path': skill_path,
            'message': f'技能 "{skill_name}" 已导入并生效',
        })

    except Exception as e:
        logger.error(f"导入技能失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
# 记忆管理 API
# ═══════════════════════════════════════════════════

@app.route('/api/memory')
def api_memory_list():
    """列出所有记忆"""
    from manage.memory_manager import MemoryManager
    mgr = MemoryManager()
    return jsonify(mgr.list_daily_memories())


@app.route('/api/memory/search')
def api_memory_search():
    """搜索记忆"""
    keyword = request.args.get('q', '')
    from manage.memory_manager import MemoryManager
    mgr = MemoryManager()
    return jsonify(mgr.search_memories(keyword))


@app.route('/api/memory/stats')
def api_memory_stats():
    """记忆统计"""
    from manage.memory_manager import MemoryManager
    mgr = MemoryManager()
    return jsonify(mgr.get_stats())


@app.route('/api/memory/<filename>')
def api_memory_read(filename):
    """读取记忆内容"""
    from manage.memory_manager import MemoryManager
    mgr = MemoryManager()
    return jsonify(mgr.read_memory(filename))


@app.route('/api/memory', methods=['POST'])
def api_memory_create():
    """新建记忆文件"""
    data = request.get_json(force=True)
    filename = data.get('filename', '').strip()
    content = data.get('content', '')
    if not filename:
        return jsonify({'success': False, 'error': '文件名不能为空'}), 400
    if not filename.endswith('.md'):
        filename += '.md'
    # 安全检查：只允许 memory/ 目录下的文件
    if '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'success': False, 'error': '非法文件名'}), 400
    from manage.memory_manager import MemoryManager
    mgr = MemoryManager()
    import os
    fpath = os.path.join(mgr.memory_dir, filename)
    if os.path.exists(fpath):
        return jsonify({'success': False, 'error': f'文件已存在: {filename}'}), 409
    try:
        os.makedirs(mgr.memory_dir, exist_ok=True)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True, 'name': filename, 'path': fpath})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/memory/<filename>', methods=['PUT'])
def api_memory_update(filename):
    """更新记忆内容"""
    data = request.get_json(force=True)
    content = data.get('content', '')
    if filename == 'MEMORY.md':
        return jsonify({'success': False, 'error': '不能通过 API 编辑 MEMORY.md'}), 403
    if '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'success': False, 'error': '非法文件名'}), 400
    from manage.memory_manager import MemoryManager
    mgr = MemoryManager()
    import os, shutil
    from datetime import datetime
    fpath = os.path.join(mgr.memory_dir, filename)
    if not os.path.isfile(fpath):
        return jsonify({'success': False, 'error': f'文件不存在: {filename}'}), 404
    try:
        # 备份
        trash_dir = os.path.join(mgr.memory_dir, '.trash')
        os.makedirs(trash_dir, exist_ok=True)
        backup = os.path.join(trash_dir, f'{filename}.{datetime.now().strftime("%Y%m%d%H%M%S")}.bak')
        shutil.copy2(fpath, backup)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True, 'name': filename, 'backup': backup})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/memory/<filename>', methods=['DELETE'])
def api_memory_delete(filename):
    """删除记忆"""
    from manage.memory_manager import MemoryManager
    mgr = MemoryManager()
    return jsonify(mgr.delete_memory(filename, confirm=True))


# ═══════════════════════════════════════════════════
# 权限管理 API（前端「权限」页面调用）
# ═══════════════════════════════════════════════════

_PERMISSIONS_FILE = os.path.join(os.path.dirname(__file__), 'data', 'permissions.json')

# ═══ 全局权限（后端权威源，PUT 时更新，所有会话共享） ═══
_global_permissions = {
    'toolWhitelist': [],
    'toolBlacklist': [],
    'skillWhitelist': [],
    'skillBlacklist': [],
    'riskTolerance': 1.0,
}

def _load_permissions() -> dict:
    """从文件加载权限配置"""
    global _global_permissions
    try:
        if os.path.isfile(_PERMISSIONS_FILE):
            with open(_PERMISSIONS_FILE, 'r', encoding='utf-8') as f:
                _global_permissions = json.load(f)
    except Exception:
        pass
    return _global_permissions

def _save_permissions(perm: dict):
    """保存权限配置到文件 + 更新全局内存（立即对所有会话生效）"""
    global _global_permissions
    os.makedirs(os.path.dirname(_PERMISSIONS_FILE), exist_ok=True)
    with open(_PERMISSIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(perm, f, ensure_ascii=False, indent=2)
    _global_permissions = perm
    logger.info("全局权限已更新（内存 + 文件）")

# 启动时加载一次
_load_permissions()

@app.route('/api/permissions', methods=['GET'])
def api_permissions_get():
    """获取权限配置"""
    return jsonify({'success': True, 'permissions': _load_permissions()})

@app.route('/api/permissions', methods=['PUT'])
def api_permissions_put():
    """更新权限配置（写入文件 + 立即更新全局内存，所有会话即时生效）"""
    try:
        data = request.get_json(force=True)
        old = dict(_global_permissions)
        perm = {
            'toolWhitelist': data.get('toolWhitelist', []),
            'toolBlacklist': data.get('toolBlacklist', []),
            'skillWhitelist': data.get('skillWhitelist', []),
            'skillBlacklist': data.get('skillBlacklist', []),
            'riskTolerance': float(data.get('riskTolerance', 1.0)),
        }
        _save_permissions(perm)

        # 生成变更摘要
        changes = []
        old_bl = set(old.get('toolBlacklist', []))
        new_bl = set(perm['toolBlacklist'])
        added_bl = new_bl - old_bl
        removed_bl = old_bl - new_bl
        if added_bl:
            changes.append(f"新增禁止工具: {', '.join(added_bl)}")
        if removed_bl:
            changes.append(f"解除禁止工具: {', '.join(removed_bl)}")
        if old.get('riskTolerance') != perm['riskTolerance']:
            risk_labels = {1.0: '允许所有', 0.8: '拦截高风险', 0.5: '仅中低风险', 0.2: '仅低风险'}
            changes.append(f"风险容忍度: {risk_labels.get(old.get('riskTolerance'), old.get('riskTolerance'))} → {risk_labels.get(perm['riskTolerance'], perm['riskTolerance'])}")

        summary = '；'.join(changes) if changes else '无实质变更'
        logger.info(f"权限已更新: {summary}")
        return jsonify({'success': True, 'message': '权限已保存并立即对所有会话生效', 'summary': summary})
    except Exception as e:
        logger.error(f"保存权限失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══ 审计日志 API（Phase 3 新增） ═══

@app.route('/api/permissions/audit-log')
def api_audit_log():
    """获取审计日志"""
    try:
        from security.filesystem_guard import guard
        limit = request.args.get('limit', 100, type=int)
        result_filter = request.args.get('result', None)
        entries = guard.get_audit_log(limit=limit, result_filter=result_filter)
        stats = guard.get_audit_stats()
        return jsonify({'success': True, 'entries': entries, 'stats': stats})
    except Exception as e:
        return jsonify({'success': True, 'entries': [], 'stats': {}})


@app.route('/api/permissions/audit-log', methods=['DELETE'])
def api_audit_log_clear():
    """清空审计日志"""
    try:
        from security.filesystem_guard import guard
        guard.clear_audit_log()
        return jsonify({'success': True, 'message': '审计日志已清空'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══ 完整配置 API（Phase 3 新增） ═══

@app.route('/api/settings/full')
def api_settings_full():
    """获取完整配置"""
    try:
        import config
        return jsonify({'success': True, 'settings': config.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/settings/full', methods=['PUT'])
def api_settings_full_update():
    """更新完整配置 + 热重载"""
    try:
        import config
        data = request.get_json(force=True)
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        updates = {}

        # LLM
        llm = data.get('llm', {})
        if llm.get('apiKey'): updates['LLM_API_KEY'] = llm['apiKey']
        if 'baseUrl' in llm: updates['LLM_BASE_URL'] = llm['baseUrl']
        if 'model' in llm: updates['LLM_MODEL'] = llm['model']
        if 'maxTokens' in llm: updates['LLM_MAX_TOKENS'] = str(llm['maxTokens'])
        if 'temperature' in llm: updates['LLM_TEMPERATURE'] = str(llm['temperature'])
        if 'timeout' in llm: updates['LLM_TIMEOUT'] = str(llm['timeout'])

        # Agent
        agent = data.get('agent', {})
        if 'maxToolCalls' in agent: updates['MAX_TOOL_CALLS'] = str(agent['maxToolCalls'])
        if 'maxContextTurns' in agent: updates['MAX_CONTEXT_TURNS'] = str(agent['maxContextTurns'])
        if 'toolTimeout' in agent: updates['TOOL_TIMEOUT'] = str(agent['toolTimeout'])

        # Security
        sec = data.get('security', {})
        if 'enabled' in sec: updates['SECURITY_ENABLED'] = str(sec['enabled']).lower()
        if 'rateWindow' in sec: updates['SECURITY_RATE_WINDOW'] = str(sec['rateWindow'])
        if 'rateMaxOps' in sec: updates['SECURITY_RATE_MAX_OPS'] = str(sec['rateMaxOps'])
        if 'allowedPaths' in sec: updates['ALLOWED_PATHS'] = str(sec['allowedPaths'])

        # Memory
        mem = data.get('memory', {})
        if 'autoMemo' in mem: updates['AUTO_MEMO'] = str(mem['autoMemo']).lower()
        if 'compressAfterTurns' in mem: updates['MAX_CONTEXT_TURNS'] = str(mem['compressAfterTurns'])

        # 写入 .env
        _write_env(updates)

        # 热重载
        config.reload_config()

        return jsonify({'success': True, 'message': '配置已保存并立即生效'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _write_env(updates):
    """写入 .env 文件"""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    lines = []
    if os.path.isfile(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

    new_lines = []
    found_keys = set()
    for line in lines:
        key = line.split('=')[0].strip() if '=' in line else ''
        if key in updates:
            new_lines.append(f'{key}={updates[key]}\n')
            found_keys.add(key)
        else:
            new_lines.append(line)
    for key, val in updates.items():
        if key not in found_keys:
            new_lines.append(f'{key}={val}\n')

    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    for key, val in updates.items():
        os.environ[key] = val


# ═══ 系统诊断 API（Phase 3 新增） ═══

@app.route('/api/diagnostics')
def api_diagnostics():
    """系统诊断"""
    import sys
    result = {
        'python_version': sys.version.split()[0],
        'platform': sys.platform,
    }

    # 工具数
    try:
        from tools.registry import registry
        all_tools = registry.get_all()
        result['tools_total'] = len(all_tools)
        result['tools_available'] = len([t for t in all_tools if t.is_available()])
    except Exception:
        result['tools_total'] = 0
        result['tools_available'] = 0

    # 技能数
    try:
        from skills.loader import load_all_skills
        skills = load_all_skills()
        result['skills_count'] = len(skills)
    except Exception:
        result['skills_count'] = 0

    # LLM 配置 + 连通性
    try:
        import config
        result['llm_configured'] = bool(config.LLM_API_KEY and not config.LLM_API_KEY.startswith('your-'))
        result['llm_model'] = config.LLM_MODEL
        result['llm_base_url'] = config.LLM_BASE_URL

        # 快速连通性测试（只发一条短消息）
        if result['llm_configured']:
            try:
                import httpx
                resp = httpx.post(
                    f"{config.LLM_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"},
                    json={"model": config.LLM_MODEL, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                    timeout=10.0,
                )
                result['llm_reachable'] = resp.status_code == 200
                if resp.status_code != 200:
                    result['llm_error'] = f"HTTP {resp.status_code}"
            except Exception as e:
                result['llm_reachable'] = False
                result['llm_error'] = str(e)[:100]
        else:
            result['llm_reachable'] = False
    except Exception:
        result['llm_configured'] = False

    # DB 大小
    import glob
    db_files = glob.glob(os.path.join(os.path.dirname(__file__), 'data', '*.db'))
    result['databases'] = []
    total_db_size = 0
    for db in db_files:
        size = os.path.getsize(db)
        total_db_size += size
        result['databases'].append({
            'name': os.path.basename(db),
            'size_kb': round(size / 1024, 1),
        })
    result['total_db_size_kb'] = round(total_db_size / 1024, 1)

    # 安全状态
    try:
        import config
        result['security_enabled'] = getattr(config, 'SECURITY_ENABLED', True)
    except Exception:
        result['security_enabled'] = False

    # 活跃会话数
    result['active_sessions'] = len(_sessions)

    return jsonify(result)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--host', default='0.0.0.0')
    args = parser.parse_args()

    print(f'\n🤖 My-Agent V2.0 Web 服务启动')
    print(f'   地址: http://localhost:{args.port}')
    print(f'   API:  http://localhost:{args.port}/api/chat')
    print(f'   健康: http://localhost:{args.port}/api/health')
    print(f'   诊断: http://localhost:{args.port}/api/diagnostics')
    print()

    app.run(host=args.host, port=args.port, debug=False, threaded=True)
