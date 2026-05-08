"""
文件操作插件 — read/write/edit/list/scan/find/move/batch_move/organize/rollback
从 builtin.py 拆分，自注册到 ToolRegistry
"""
import os
import json
import shutil
import datetime
import glob as glob_mod

from tools.registry import registry
from tools.tool_utils import (
    structured_error, classify_os_error, categorize_file,
    get_special_folder, human_size, _EXT_CATEGORIES,
    ToolResult, normalize_path,
)


# ═══ read_file ═══

def _read_file(path: str) -> str:
    path = normalize_path(path)
    if not os.path.exists(path):
        return ToolResult.fail(f"文件不存在: {path}", "E_NOT_FOUND",
                               hint="检查路径是否正确，或用 find_files 搜索文件名。", path=path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return ToolResult.ok({"path": path, "size": len(content), "content": content[:50000]})
    except PermissionError:
        return ToolResult.fail(f"没有权限读取: {path}", "E_PERMISSION",
                               hint="文件可能被其他程序占用，或权限不足。", path=path)
    except UnicodeDecodeError:
        return ToolResult.fail(f"无法以 UTF-8 读取: {path}", "E_ENCODING",
                               hint="文件可能是二进制文件或使用了其他编码。试试用 run_command(type/cat) 读取。", path=path)
    except Exception as e:
        return classify_os_error(e, path) if isinstance(e, OSError) else ToolResult.fail(
            f"读取失败: {e}", "E_UNKNOWN", recoverable=False, path=path)


registry.register(
    name="read_file",
    description="读取文件内容",
    schema={
        "name": "read_file",
        "description": "读取文件内容",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（绝对或相对）"}
            },
            "required": ["path"]
        }
    },
    handler=_read_file,
    category="file",
    risk_level="low",
)


# ═══ write_file ═══

def _write_file(path: str, content: str) -> str:
    if not path or not path.strip():
        return ToolResult.fail("路径不能为空", "E_INVALID_PATH",
                               hint="请提供完整的文件路径，如 'main.py' 或 'D:\\project\\main.py'")
    path = normalize_path(path.strip())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return ToolResult.ok({"path": path, "bytes": len(content)})
    except PermissionError:
        return ToolResult.fail(f"没有权限写入: {path}", "E_PERMISSION",
                               hint="目标目录可能受保护，或文件被其他程序占用。", path=path)
    except OSError as e:
        return classify_os_error(e, path)
    except Exception as e:
        return ToolResult.fail(f"写入失败: {e}", "E_UNKNOWN", recoverable=False, path=path)


registry.register(
    name="write_file",
    description="创建或写入文件",
    schema={
        "name": "write_file",
        "description": "创建或写入文件",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"}
            },
            "required": ["path", "content"]
        }
    },
    handler=_write_file,
    category="file",
    risk_level="medium",
)


# ═══ edit_file ═══

def _edit_file(path: str, old_text: str, new_text: str) -> str:
    path = normalize_path(path)
    if not os.path.exists(path):
        return ToolResult.fail(f"文件不存在: {path}", "E_NOT_FOUND",
                               hint="检查路径是否正确。", path=path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except PermissionError:
        return ToolResult.fail(f"没有权限读取: {path}", "E_PERMISSION", path=path)
    except UnicodeDecodeError:
        return ToolResult.fail(f"无法以 UTF-8 读取: {path}", "E_ENCODING",
                               hint="文件可能不是 UTF-8 编码。", path=path)
    if old_text not in content:
        return ToolResult.fail("未找到要替换的文本", "E_NOT_FOUND",
                               hint="old_text 在文件中不存在。检查是否有空格、换行、缩进差异。用 read_file 先看一下实际内容。",
                               recoverable=True, path=path)
    content = content.replace(old_text, new_text, 1)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except PermissionError:
        return ToolResult.fail(f"没有权限写入: {path}", "E_PERMISSION", path=path)
    return ToolResult.ok({"path": path})


registry.register(
    name="edit_file",
    description="精确编辑文件（查找替换）",
    schema={
        "name": "edit_file",
        "description": "精确编辑文件（查找替换）",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "old_text": {"type": "string", "description": "要替换的原文"},
                "new_text": {"type": "string", "description": "替换后的内容"}
            },
            "required": ["path", "old_text", "new_text"]
        }
    },
    handler=_edit_file,
    category="file",
    risk_level="medium",
)


# ═══ list_files ═══

def _list_files(path: str = ".", pattern: str = "*") -> str:
    path = normalize_path(path)
    if not os.path.isdir(path):
        return ToolResult.fail(f"目录不存在: {path}", "E_NOT_FOUND", path=path)
    files = []
    for f in glob_mod.glob(os.path.join(path, pattern)):
        rel = os.path.relpath(f, path)
        is_dir = os.path.isdir(f)
        size = 0 if is_dir else os.path.getsize(f)
        files.append({"name": rel, "is_dir": is_dir, "size": size})
    return json.dumps({"path": path, "files": files[:100]})


registry.register(
    name="list_files",
    description="列出目录下的文件",
    schema={
        "name": "list_files",
        "description": "列出目录下的文件",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径", "default": "."},
                "pattern": {"type": "string", "description": "文件模式（如 *.py）", "default": "*"}
            }
        }
    },
    handler=_list_files,
    category="file",
    risk_level="low",
)


# ═══ scan_files ═══

def _scan_files(path: str = ".", recursive: bool = False, include_hidden: bool = False) -> str:
    path = normalize_path(path)

    if not os.path.isdir(path):
        if "Desktop" in path or "desktop" in path:
            alt = get_special_folder("Desktop")
            if os.path.isdir(alt):
                path = alt
        elif "Downloads" in path or "downloads" in path:
            alt = get_special_folder("Downloads")
            if os.path.isdir(alt):
                path = alt

    if not os.path.isdir(path):
        return json.dumps({"error": f"目录不存在: {path}"})

    files = []
    categories = {}

    if recursive:
        for root, dirs, filenames in os.walk(path):
            if not include_hidden:
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                filenames = [f for f in filenames if not f.startswith(".")]
            for fname in filenames:
                fpath = os.path.join(root, fname)
                rel_path = os.path.relpath(fpath, path)
                try:
                    stat = os.stat(fpath)
                    ext = os.path.splitext(fname)[1].lower()
                    cat = categorize_file(fname)
                    files.append({
                        "name": fname, "path": rel_path, "ext": ext,
                        "size": stat.st_size, "size_human": human_size(stat.st_size),
                        "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "category": cat,
                    })
                    categories[cat] = categories.get(cat, 0) + 1
                except OSError:
                    continue
    else:
        try:
            entries = sorted(os.listdir(path))
        except OSError as e:
            return json.dumps({"error": str(e)})

        for fname in entries:
            if not include_hidden and fname.startswith("."):
                continue
            fpath = os.path.join(path, fname)
            try:
                stat = os.stat(fpath)
                ext = os.path.splitext(fname)[1].lower()
                cat = categorize_file(fname)
                is_dir = os.path.isdir(fpath)
                files.append({
                    "name": fname, "is_dir": is_dir, "ext": ext if not is_dir else "",
                    "size": 0 if is_dir else stat.st_size,
                    "size_human": "📁" if is_dir else human_size(stat.st_size),
                    "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "category": "目录" if is_dir else cat,
                })
                if not is_dir:
                    categories[cat] = categories.get(cat, 0) + 1
            except OSError:
                continue

    return json.dumps({
        "path": path, "total": len(files), "categories": categories, "files": files[:200],
    }, ensure_ascii=False)


registry.register(
    name="scan_files",
    description="扫描目录，返回带元数据的文件列表。每个文件包含名称、大小、修改时间、扩展名和自动分类。用于了解目录结构和文件分布。",
    schema={
        "name": "scan_files",
        "description": "扫描目录，返回带元数据的文件列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要扫描的目录路径", "default": "."},
                "recursive": {"type": "boolean", "description": "是否递归扫描子目录", "default": False},
                "include_hidden": {"type": "boolean", "description": "是否包含隐藏文件（以.开头）", "default": False}
            }
        }
    },
    handler=_scan_files,
    category="file",
    risk_level="low",
)


# ═══ find_files ═══

def _find_files(path: str = ".", name: str = "", ext: str = "",
                modified_after: str = "", modified_before: str = "",
                min_size: int = 0, max_size: int = 0, max_results: int = 50) -> str:
    path = normalize_path(path)
    if not os.path.isdir(path):
        return json.dumps({"error": f"目录不存在: {path}"})

    dt_after = dt_before = None
    if modified_after:
        try:
            dt_after = datetime.datetime.strptime(modified_after, "%Y-%m-%d")
        except ValueError:
            pass
    if modified_before:
        try:
            dt_before = datetime.datetime.strptime(modified_before, "%Y-%m-%d")
        except ValueError:
            pass

    results = []
    name_lower = name.lower()
    ext_lower = ext.lower() if ext else ""

    for root, dirs, filenames in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in filenames:
            if fname.startswith("."):
                continue
            fext = os.path.splitext(fname)[1].lower()
            if ext_lower and fext != ext_lower:
                continue
            if name_lower and name_lower not in fname.lower():
                continue
            fpath = os.path.join(root, fname)
            try:
                stat = os.stat(fpath)
            except OSError:
                continue
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
            if dt_after and mtime < dt_after:
                continue
            if dt_before and mtime > dt_before:
                continue
            if min_size and stat.st_size < min_size:
                continue
            if max_size and stat.st_size > max_size:
                continue
            rel_path = os.path.relpath(fpath, path)
            results.append({
                "name": fname, "path": rel_path, "full_path": fpath, "ext": fext,
                "size": stat.st_size, "size_human": human_size(stat.st_size),
                "modified": mtime.isoformat(), "category": categorize_file(fname),
            })

    results.sort(key=lambda x: x["modified"], reverse=True)
    results = results[:max_results]
    return json.dumps({
        "path": path,
        "query": {"name": name, "ext": ext, "after": modified_after, "before": modified_before},
        "total": len(results), "results": results,
    }, ensure_ascii=False)


registry.register(
    name="find_files",
    description="搜索文件。支持按名称（模糊匹配）、扩展名、日期范围、大小范围搜索。返回按相关度排序的结果列表。",
    schema={
        "name": "find_files",
        "description": "搜索文件。支持按名称、扩展名、日期范围、大小范围搜索。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "搜索起始目录", "default": "."},
                "name": {"type": "string", "description": "文件名关键词（模糊匹配）", "default": ""},
                "ext": {"type": "string", "description": "文件扩展名过滤（如 .py, .pdf）", "default": ""},
                "modified_after": {"type": "string", "description": "只返回此日期之后修改的文件（格式 YYYY-MM-DD）", "default": ""},
                "modified_before": {"type": "string", "description": "只返回此日期之前修改的文件（格式 YYYY-MM-DD）", "default": ""},
                "min_size": {"type": "integer", "description": "最小文件大小（字节）", "default": 0},
                "max_size": {"type": "integer", "description": "最大文件大小（字节，0=不限）", "default": 0},
                "max_results": {"type": "integer", "description": "最大返回数量", "default": 50}
            }
        }
    },
    handler=_find_files,
    category="file",
    risk_level="low",
)


# ═══ move_file ═══

def _move_file(src: str, dst: str, op_id: str = None) -> str:
    from tools import rollback

    src = normalize_path(src)
    dst = normalize_path(dst)

    if not os.path.exists(src):
        return structured_error("not_found", f"源文件不存在: {src}",
                                hint="文件可能已被移动或删除。用 find_files 搜索一下？",
                                recoverable=True, path=src)

    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))

    if os.path.exists(dst):
        try:
            src_stat = os.stat(src)
            dst_stat = os.stat(dst)
            src_mtime = datetime.datetime.fromtimestamp(src_stat.st_mtime).isoformat()
            dst_mtime = datetime.datetime.fromtimestamp(dst_stat.st_mtime).isoformat()
            return json.dumps({
                "error": "conflict", "message": f"目标已存在同名文件",
                "src": src, "dst": dst,
                "src_info": {
                    "size": src_stat.st_size, "size_human": human_size(src_stat.st_size),
                    "modified": src_mtime, "category": categorize_file(os.path.basename(src)),
                },
                "dst_info": {
                    "size": dst_stat.st_size, "size_human": human_size(dst_stat.st_size),
                    "modified": dst_mtime, "category": categorize_file(os.path.basename(dst)),
                },
                "options": ["skip — 跳过此文件", "rename — 自动重命名（在文件名后加序号）", "overwrite — 覆盖目标文件（不可恢复）"],
                "hint": "请告诉用户两个文件的大小和日期对比，让用户选择处理方式。默认建议「两个都保留（重命名）」。",
            }, ensure_ascii=False)
        except OSError:
            return json.dumps({"error": "conflict", "message": f"目标已存在同名文件: {dst}", "src": src, "dst": dst}, ensure_ascii=False)

    if op_id is None:
        op_id = rollback.start_operation("自动文件操作")
    entry = rollback.record_move(src, dst)

    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        rollback.add_entry(op_id, entry)
        return json.dumps({"success": True, "src": src, "dst": dst, "op_id": op_id, "category": categorize_file(os.path.basename(dst))}, ensure_ascii=False)
    except OSError as e:
        if getattr(e, 'errno', None) == 18 or 'cross-device' in str(e).lower():
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                    shutil.rmtree(src)
                else:
                    shutil.copy2(src, dst)
                    os.remove(src)
                rollback.add_entry(op_id, entry)
                return json.dumps({"success": True, "src": src, "dst": dst, "op_id": op_id, "method": "copy+delete (跨设备自动重试)", "category": categorize_file(os.path.basename(dst))}, ensure_ascii=False)
            except Exception as e2:
                return classify_os_error(e2, src)
        return classify_os_error(e, src)
    except Exception as e:
        return structured_error("move_failed", f"移动失败: {e}", recoverable=False, src=src, dst=dst)


registry.register(
    name="move_file",
    description="移动文件或目录到目标位置。自动记录回滚点，用户可随时恢复。如果目标已存在同名文件，返回冲突信息而不是覆盖。",
    schema={
        "name": "move_file",
        "description": "移动文件或目录到目标位置。自动记录回滚点。",
        "parameters": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "源文件路径"},
                "dst": {"type": "string", "description": "目标路径（可以是目录或完整文件名）"},
                "op_id": {"type": "string", "description": "回滚操作组 ID", "default": None}
            },
            "required": ["src", "dst"]
        }
    },
    handler=_move_file,
    category="file",
    risk_level="medium",
)


# ═══ batch_move ═══

def _batch_move(moves: list, description: str = "批量文件移动") -> str:
    from tools import rollback

    op_id = rollback.start_operation(description)
    results = []
    success_count = error_count = 0

    for m in moves:
        src = normalize_path(m.get("src", ""))
        dst = normalize_path(m.get("dst", ""))

        if not src or not dst:
            results.append({"src": src, "dst": dst, "status": "error", "reason": "路径为空"})
            error_count += 1
            continue
        if not os.path.exists(src):
            results.append({"src": src, "dst": dst, "status": "error", "reason": "源文件不存在"})
            error_count += 1
            continue
        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))
        if os.path.exists(dst):
            results.append({"src": src, "dst": dst, "status": "conflict", "reason": "目标已存在"})
            error_count += 1
            continue

        entry = rollback.record_move(src, dst)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            rollback.add_entry(op_id, entry)
            results.append({"src": src, "dst": dst, "status": "moved", "category": categorize_file(os.path.basename(dst))})
            success_count += 1
        except OSError as e:
            if getattr(e, 'errno', None) == 18 or 'cross-device' in str(e).lower():
                try:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                        shutil.rmtree(src)
                    else:
                        shutil.copy2(src, dst)
                        os.remove(src)
                    rollback.add_entry(op_id, entry)
                    results.append({"src": src, "dst": dst, "status": "moved", "method": "copy+delete", "category": categorize_file(os.path.basename(dst))})
                    success_count += 1
                    continue
                except Exception:
                    pass
            results.append({"src": src, "dst": dst, "status": "error", "reason": str(e), "recoverable": True})
            error_count += 1
        except Exception as e:
            results.append({"src": src, "dst": dst, "status": "error", "reason": str(e), "recoverable": False})
            error_count += 1

    rollback.complete_operation(op_id)
    return json.dumps({
        "op_id": op_id, "total": len(moves), "success": success_count, "errors": error_count,
        "results": results, "rollback_hint": f"如果需要撤销，告诉我「回滚 {op_id}」",
    }, ensure_ascii=False)


registry.register(
    name="batch_move",
    description="批量移动文件。传入文件映射列表，一次操作完成所有移动。自动归为同一个回滚操作组，支持一键全部撤销。",
    schema={
        "name": "batch_move",
        "description": "批量移动文件。自动归为同一个回滚操作组。",
        "parameters": {
            "type": "object",
            "properties": {
                "moves": {
                    "type": "array", "description": "移动映射列表，每项包含 src 和 dst",
                    "items": {"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]}
                },
                "description": {"type": "string", "description": "操作描述", "default": "批量文件移动"}
            },
            "required": ["moves"]
        }
    },
    handler=_batch_move,
    category="file",
    risk_level="medium",
)


# ═══ rollback_operation ═══

def _rollback_operation(op_id: str = None) -> str:
    from tools import rollback
    if op_id is None:
        ops = rollback.list_operations()
        if not ops:
            return json.dumps({"error": "没有可回滚的操作记录"})
        op_id = ops[0]["op_id"]
    result = rollback.rollback(op_id)
    if "user_message" in result:
        result["display_message"] = result["user_message"]
    return json.dumps(result, ensure_ascii=False)


registry.register(
    name="rollback_operation",
    description="回滚之前的文件操作。可以回滚最近一次操作，或指定操作 ID。恢复所有被移动的文件到原始位置。",
    schema={
        "name": "rollback_operation",
        "description": "回滚之前的文件操作。",
        "parameters": {
            "type": "object",
            "properties": {
                "op_id": {"type": "string", "description": "要回滚的操作 ID。不传则回滚最近一次操作。", "default": None}
            }
        }
    },
    handler=_rollback_operation,
    category="file",
    risk_level="medium",
)


# ═══ list_rollback_history ═══

def _list_rollback_history() -> str:
    from tools import rollback
    ops = rollback.list_operations(include_rolled_back=True)
    return json.dumps({"total": len(ops), "operations": ops}, ensure_ascii=False)


registry.register(
    name="list_rollback_history",
    description="列出所有回滚操作历史记录。查看之前做过哪些文件操作，以及是否已回滚。",
    schema={
        "name": "list_rollback_history",
        "description": "列出所有回滚操作历史记录。",
        "parameters": {"type": "object", "properties": {}}
    },
    handler=_list_rollback_history,
    category="file",
    risk_level="low",
)


# ═══ organize_directory ═══

def _organize_directory(path: str, dry_run: bool = False, exclude: list = None,
                        custom_categories: dict = None) -> str:
    from tools import rollback

    path = normalize_path(path)

    if not os.path.isdir(path):
        if "Desktop" in path or "desktop" in path:
            alt = get_special_folder("Desktop")
            if os.path.isdir(alt):
                path = alt
        elif "Downloads" in path or "downloads" in path:
            alt = get_special_folder("Downloads")
            if os.path.isdir(alt):
                path = alt

    if not os.path.isdir(path):
        return json.dumps({"error": f"目录不存在: {path}"})

    exclude = set(exclude or [])
    custom_categories = custom_categories or {}

    try:
        entries = os.listdir(path)
    except OSError as e:
        return json.dumps({"error": str(e)})

    files = []
    dirs_already = []
    for fname in entries:
        if fname.startswith(".") or fname in exclude:
            continue
        fpath = os.path.join(path, fname)
        if os.path.isdir(fpath):
            dirs_already.append(fname)
            continue
        if os.path.isfile(fpath):
            files.append((fname, fpath))

    if not files:
        return json.dumps({"message": "目录已经是空的或只有文件夹，无需整理", "path": path, "existing_dirs": dirs_already})

    categories = {}
    uncertain = []

    for fname, fpath in files:
        cat = None
        if custom_categories:
            for keyword, target_cat in custom_categories.items():
                if keyword.lower() in fname.lower():
                    cat = target_cat
                    break
        if cat is None:
            cat = categorize_file(fname)
        if cat == "其他":
            uncertain.append((fname, fpath))
        else:
            categories.setdefault(cat, []).append((fname, fpath))

    summary = {}
    for cat, items in categories.items():
        summary[cat] = {"count": len(items), "files": [f for f, _ in items[:10]], "extra": len(items) - 10 if len(items) > 10 else 0}
    if uncertain:
        summary["⚠️ 不确定"] = {"count": len(uncertain), "files": [f for f, _ in uncertain[:10]], "extra": len(uncertain) - 10 if len(uncertain) > 10 else 0, "hint": "这些文件无法自动分类，请用户决定如何处理"}

    if dry_run:
        return json.dumps({"mode": "preview", "path": path, "total_files": len(files), "categories": summary,
                           "message": f"将整理 {len(files)} 个文件到 {len(categories)} 个分类文件夹" + (f"，{len(uncertain)} 个文件无法分类" if uncertain else "")}, ensure_ascii=False)

    op_id = rollback.start_operation(f"整理目录: {path}")
    moved_count = 0
    skipped = []
    move_errors = []

    for cat, items in categories.items():
        cat_dir = os.path.join(path, cat)
        try:
            os.makedirs(cat_dir, exist_ok=True)
            rollback.add_entry(op_id, rollback.record_create(cat_dir))
        except OSError as e:
            move_errors.append({"category": cat, "error": str(e)})
            continue

        for fname, fpath in items:
            dst = os.path.join(cat_dir, fname)
            if os.path.exists(dst):
                base, ext = os.path.splitext(fname)
                counter = 1
                while os.path.exists(dst):
                    dst = os.path.join(cat_dir, f"{base}_{counter}{ext}")
                    counter += 1
                skipped.append({"file": fname, "reason": f"同名已存在，重命名为 {os.path.basename(dst)}"})
            entry = rollback.record_move(fpath, dst)
            try:
                shutil.move(fpath, dst)
                rollback.add_entry(op_id, entry)
                moved_count += 1
            except Exception as e:
                move_errors.append({"file": fname, "error": str(e)})

    rollback.complete_operation(op_id)

    try:
        from tools.file_monitor import mark_cleanup, DEFAULT_WATCH_DIRS
        for dir_path, dir_label in DEFAULT_WATCH_DIRS:
            if os.path.abspath(os.path.expanduser(dir_path)) == os.path.abspath(path):
                mark_cleanup(dir_label)
                break
        else:
            mark_cleanup(os.path.basename(path))
    except Exception:
        pass

    return json.dumps({
        "success": True, "op_id": op_id, "path": path, "total_files": len(files),
        "moved": moved_count, "categories": {cat: len(items) for cat, items in categories.items()},
        "uncertain": len(uncertain), "uncertain_files": [f for f, _ in uncertain[:20]],
        "skipped": skipped[:10], "errors": move_errors[:10],
        "rollback_hint": f"说「恢复 {op_id}」可一键撤销本次整理",
        "display_hint": "告诉用户：已整理完成，列出各分类文件数量，提示不确定的文件留给用户处理，并说明如何撤销。",
    }, ensure_ascii=False)


registry.register(
    name="organize_directory",
    description="一键整理目录。自动扫描 → 按扩展名分类 → 创建分类文件夹 → 移动文件。整个操作自动归为同一个回滚组，用户说「恢复」即可一键撤销。",
    schema={
        "name": "organize_directory",
        "description": "一键整理目录。自动扫描、分类、移动文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要整理的目录路径"},
                "dry_run": {"type": "boolean", "description": "预览模式：只返回分类方案，不实际移动文件", "default": False},
                "exclude": {"type": "array", "description": "排除的文件名列表", "items": {"type": "string"}, "default": []},
                "custom_categories": {"type": "object", "description": "自定义分类覆盖", "default": {}}
            },
            "required": ["path"]
        }
    },
    handler=_organize_directory,
    category="file",
    risk_level="medium",
)
