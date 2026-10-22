from app.logging_setup import log
from app.tools.registry import ToolResult
import os
import sys
import ast
import difflib
import fnmatch
from html import escape
from typing import Dict, Any, Optional

from app.storage.workspace import get_workspace_dir, resolve_path, walk_workspace

_resolve_safe_path = resolve_path


def _format_function_signature(node: ast.FunctionDef) -> str:
    """提取函式簽名與參數型別"""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret_str = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    start_line = getattr(node, "lineno", "?")
    end_line = getattr(node, "end_lineno", "?")
    return f"{prefix} {node.name}({ast.unparse(node.args)}){ret_str} [L{start_line}-L{end_line}]"


def parse_py_ast(file_path: str, *, parsed_files=None) -> Dict[str, Any]:
    """使用 Python 內建 AST 解析 .py 檔案的結構骨架"""
    rel_path = os.path.relpath(file_path, get_workspace_dir())
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            code = f.read()
        
        lines = code.splitlines()
        tree = ast.parse(code, filename=file_path)
        if parsed_files is not None:
            parsed_files[file_path] = tree
    except SyntaxError as e:
        if parsed_files is not None:
            parsed_files[file_path] = e
        log("workspace.parse_failed", level=40, exc_info=True, file=file_path)
        return {
            "file": rel_path,
            "status": "syntax_error",
            "error": f"語法錯誤 (Line {e.lineno}): {e.msg}",
            "lines": 0,
            "items": []
        }
    except Exception as e:
        if parsed_files is not None:
            parsed_files[file_path] = e
        log("workspace.exception", level=40, exc_info=True)
        return {
            "file": rel_path,
            "status": "error",
            "error": str(e),
            "lines": 0,
            "items": []
        }

    items = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            cls_doc = ast.get_docstring(node) or ""
            cls_doc_first = cls_doc.split("\n")[0].strip() if cls_doc else ""
            methods = []
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_sig = _format_function_signature(child)
                    fn_doc = ast.get_docstring(child) or ""
                    fn_doc_first = fn_doc.split("\n")[0].strip() if fn_doc else ""
                    methods.append({
                        "name": child.name,
                        "signature": fn_sig,
                        "doc": fn_doc_first,
                        "start_line": getattr(child, "lineno", 0),
                        "end_line": getattr(child, "end_lineno", 0),
                    })
            items.append({
                "type": "class",
                "name": node.name,
                "doc": cls_doc_first,
                "start_line": getattr(node, "lineno", 0),
                "end_line": getattr(node, "end_lineno", 0),
                "methods": methods
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_sig = _format_function_signature(node)
            fn_doc = ast.get_docstring(node) or ""
            fn_doc_first = fn_doc.split("\n")[0].strip() if fn_doc else ""
            items.append({
                "type": "function",
                "name": node.name,
                "signature": fn_sig,
                "doc": fn_doc_first,
                "start_line": getattr(node, "lineno", 0),
                "end_line": getattr(node, "end_lineno", 0),
            })

    return {
        "file": rel_path,
        "status": "ok",
        "lines": len(lines),
        "items": items
    }


def _walk_scope(nodes):
    """走訪目前作用域，避免把巢狀函式的呼叫算到外層。"""
    stack = list(reversed(nodes))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def build_workspace_directed_graph(workspace_dir: str = None, node_targets: Optional[Dict] = None, *, parsed_files=None) -> str:
    """先索引全庫，再解析包含、呼叫與繼承關係；無法靜態判定的呼叫略過。"""
    workspace_dir = workspace_dir or get_workspace_dir()
    lines = [
        "graph TD",
        "  classDef fileNode fill:#0f172a,stroke:#334155,stroke-width:2px,color:#f8fafc;",
        "  classDef classNode fill:#1e1b4b,stroke:#4338ca,stroke-width:2px,color:#e0e7ff;",
        "  classDef funcNode fill:#064e3b,stroke:#059669,stroke-width:2px,color:#d1fae5;",
        "  classDef mainNode fill:#78350f,stroke:#d97706,stroke-width:2px,color:#fef3c7;",
    ]
    symbols, scopes, bases = {}, [], {}
    function_types = (ast.FunctionDef, ast.AsyncFunctionDef)

    def target(node_id, path, line=1, name=""):
        if node_targets is not None:
            node_targets[node_id] = {"path": path, "line": line, "name": name}

    def qualify(parent, name):
        return f"{parent}.{name}" if parent else name

    def imports_in(nodes, module):
        imports = {}
        for node in _walk_scope(nodes):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
            elif isinstance(node, ast.ImportFrom):
                prefix = node.module or ""
                if node.level:
                    package = module["package"].split(".") if module["package"] else []
                    package = package[:max(0, len(package) - node.level + 1)]
                    prefix = ".".join(package + ([prefix] if prefix else []))
                for alias in node.names:
                    if alias.name != "*":
                        imports[alias.asname or alias.name] = qualify(prefix, alias.name)
        return imports

    def reference(name, module, imports, owner=None, receiver=None):
        head, dot, tail = name.partition(".")
        if owner and head == receiver and dot:
            return qualify(owner, tail)
        if head in imports:
            return qualify(imports[head], tail) if dot else imports[head]
        return qualify(module["name"], name)

    def lookup(name, seen=frozenset()):
        if name in symbols:
            return name
        if name in seen:
            return None
        owner, _, member = name.rpartition(".")
        for base in bases.get(owner, []):
            found = lookup(qualify(base, member), seen | {name})
            if found:
                return found
        return None

    def add_symbol(node, module, parent_id, owner=None):
        name = qualify(owner or module["name"], node.name)
        node_id = f'symbol_{module["id"]}_{node.lineno}'
        target(node_id, module["path"], node.lineno, name)
        symbols[name] = {"id": node_id, "node": node, "module": module}
        is_class = isinstance(node, ast.ClassDef)
        label = f"📦 class {name}" if is_class else f"⚙️ {name}()"
        style = "classNode" if is_class else "funcNode"
        lines.append(f'    {node_id}["{escape(label)}<br><small>L{node.lineno}-L{node.end_lineno}</small>"]:::{style}')
        lines.append(f"    {parent_id} -->|contains| {node_id}")
        if is_class:
            for child in node.body:
                if isinstance(child, function_types):
                    add_symbol(child, module, node_id, name)
        else:
            scopes.append((node_id, module, owner, node))

    # 第一輪：每檔只解析一次，建立完整的模組、類別與方法索引。
    paths = sorted(parsed_files) if parsed_files is not None else []
    if parsed_files is None:
        for root, dirs, files in walk_workspace(workspace_dir):
            dirs.sort()
            paths.extend(os.path.join(root, file) for file in sorted(files) if file.endswith(".py"))
    if not paths:
        return 'graph TD\n  EmptyWorkspace["工作區目前無任何 Python 檔案"]'

    for index, path in enumerate(paths):
        rel_path = os.path.relpath(path, workspace_dir).replace("\\", "/")
        file_id = f"file_{index}"
        try:
            if parsed_files is not None:
                tree = parsed_files[path]
                if isinstance(tree, Exception):
                    raise tree
            else:
                with open(path, encoding="utf-8-sig") as source:
                    tree = ast.parse(source.read(), filename=rel_path)
        except (OSError, UnicodeError, SyntaxError) as error:
            lines.append(f'  {file_id}["⚠️ {escape(rel_path)}: {escape(str(error))}"]:::fileNode')
            continue

        parts = rel_path[:-3].split("/")
        is_package = parts[-1] == "__init__"
        name = ".".join(parts[:-1] if is_package else parts)
        module = {"id": file_id, "path": rel_path, "name": name, "package": name if is_package else name.rpartition(".")[0]}
        target(file_id, rel_path, name=rel_path)
        module["imports"] = imports_in(tree.body, module)
        lines.append(f'  subgraph group_{index}["{escape(rel_path)}"]')
        lines.append(f'    {file_id}["📄 {escape(rel_path)}"]:::fileNode')
        top_level = []
        for node in tree.body:
            if isinstance(node, (ast.ClassDef,) + function_types):
                add_symbol(node, module, file_id)
            elif isinstance(node, ast.If) and ast.unparse(node.test) in (
                "__name__ == '__main__'", "'__main__' == __name__"
            ):
                main_id = f"main_{index}_{node.lineno}"
                target(main_id, rel_path, node.lineno, "__main__")
                lines.append(f'    {main_id}["⚡ __main__ 入口<br><small>L{node.lineno}-L{node.end_lineno}</small>"]:::mainNode')
                lines.append(f"    {file_id} -->|contains| {main_id}")
                scopes.append((main_id, module, None, node))
            else:
                top_level.append(node)
        scopes.append((file_id, module, None, ast.Module(body=top_level, type_ignores=[])))
        lines.append("  end")

    # 第二輪：全部符號已存在，跨檔解析不再依賴掃描順序。
    for name, symbol in symbols.items():
        if isinstance(symbol["node"], ast.ClassDef):
            module = symbol["module"]
            bases[name] = [
                reference(base_name, module, module["imports"])
                for base in symbol["node"].bases
                if (base_name := _dotted_name(base))
            ]
            for base in bases[name]:
                if base in symbols and isinstance(symbols[base]["node"], ast.ClassDef):
                    lines.append(f'  {symbol["id"]} ==>|inherits| {symbols[base]["id"]}')

    call_edges = set()
    for caller_id, module, owner, scope in scopes:
        nodes = list(_walk_scope(scope.body))
        imports = {**module["imports"], **imports_in(scope.body, module)}
        bound = {node.id for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
        bound.update(node.name for node in nodes if isinstance(node, (ast.ClassDef,) + function_types))
        receiver = None
        if isinstance(scope, function_types):
            args = scope.args
            positional = args.posonlyargs + args.args
            bound.update(arg.arg for arg in positional + args.kwonlyargs)
            bound.update(arg.arg for arg in (args.vararg, args.kwarg) if arg)
            is_static = any(_dotted_name(item) == "staticmethod" for item in scope.decorator_list)
            if owner and positional and not is_static:
                receiver = positional[0].arg
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            called = _dotted_name(node.func)
            if not called:
                continue
            head = called.split(".")[0]
            if head in bound and head != receiver:
                continue
            target = lookup(reference(called, module, imports, owner, receiver))
            if target:
                call_edges.add((caller_id, symbols[target]["id"]))
    for caller_id, target_id in sorted(call_edges):
        lines.append(f"  {caller_id} -.->|calls| {target_id}")
    return "\n".join(lines)


def get_workspace_code_map(include_graph: bool = True) -> str:
    """
    【代碼庫語意地圖與有向圖 (Repo Map & Directed Graph)】
    掃描工作區，生成類別、函式簽名與行號；include_graph=True 時附加 Mermaid 呼叫關係圖。
    """
    if not os.path.exists(get_workspace_dir()):
        return "工作區目前為空，尚無任何檔案。"

    all_files = []
    for root, dirs, files in walk_workspace():
        for file in files:
            all_files.append(os.path.join(root, file))

    if not all_files:
        return "工作區目前為空，尚無任何檔案。"

    out = [f"【目前專案工作區代碼架構地圖】:"]
    py_files = [f for f in all_files if f.endswith(".py")]
    non_py_files = [f for f in all_files if not f.endswith(".py")]
    parsed_files = {} if include_graph else None

    for fpath in sorted(py_files):
        parsed = parse_py_ast(fpath, parsed_files=parsed_files)
        rel_path = parsed["file"]
        lines_cnt = parsed["lines"]
        if parsed["status"] == "syntax_error":
            out.append(f"\n📄 {rel_path} (共 {lines_cnt} 行) ⚠️ {parsed['error']}")
            continue

        out.append(f"\n📄 {rel_path} (共 {lines_cnt} 行)")
        if not parsed["items"]:
            out.append("    (無類別或獨立頂層函式)")
            continue

        for item in parsed["items"]:
            if item["type"] == "class":
                doc_str = f" - \"{item['doc']}\"" if item['doc'] else ""
                out.append(f"  ├── 📦 class {item['name']} [L{item['start_line']}-L{item['end_line']}]{doc_str}")
                for m in item.get("methods", []):
                    m_doc = f" - \"{m['doc']}\"" if m['doc'] else ""
                    out.append(f"  │    ├── ⚙️ {m['signature']}{m_doc}")
            elif item["type"] == "function":
                f_doc = f" - \"{item['doc']}\"" if item['doc'] else ""
                out.append(f"  ├── ⚙️ {item['signature']}{f_doc}")

    if non_py_files:
        out.append("\n📁 其他非 Python 檔案：")
        for fpath in sorted(non_py_files):
            rel_path = os.path.relpath(fpath, get_workspace_dir())
            sz = os.path.getsize(fpath)
            out.append(f"  └── 📄 {rel_path} ({sz} bytes)")

    if include_graph:
        graph_code = build_workspace_directed_graph(parsed_files=parsed_files)
        out.append(f"\n\n【節點調用有向圖 (Directed Call Graph - Mermaid 語法)】:\n```mermaid\n{graph_code}\n```")

    return "\n".join(out)



def search_workspace(query: str, file_pattern: str = "*", limit: int = 50) -> Dict:
    """有界的純文字搜尋，提供 API 與 Agent 工具共用。"""
    query = query.strip()
    if not query:
        return {"matches": [], "truncated": False}
    needle = query.casefold()
    limit = max(1, min(limit, 100))
    matches = []
    for root, dirs, files in walk_workspace():
        dirs[:] = sorted(d for d in dirs if d != "runtime")
        for name in sorted(files):
            relative = os.path.relpath(os.path.join(root, name), get_workspace_dir()).replace("\\", "/")
            if not (fnmatch.fnmatch(relative, file_pattern) or fnmatch.fnmatch(name, file_pattern)):
                continue
            try:
                path = _resolve_safe_path(relative)
                if os.path.getsize(path) > 1024 * 1024:
                    continue
                with open(path, encoding="utf-8-sig") as source:
                    text = source.read()
                if "\0" in text:
                    continue
            except (OSError, UnicodeError, ValueError):
                continue
            for line, content in enumerate(text.splitlines(), 1):
                if needle in content.casefold():
                    if len(matches) == limit:
                        return {"matches": matches, "truncated": True}
                    matches.append({"path": relative, "line": line, "content": content[:300]})
    return {"matches": matches, "truncated": False}


def search_workspace_code(query: str, file_pattern: str = "*", limit: int = 50) -> str:
    """搜尋程式與文件中的文字，回傳檔案、行號及片段。file_pattern 可指定 *.py 等樣式。"""
    result = search_workspace(query, file_pattern, limit)
    lines = [f"{item['path']}:{item['line']} | {item['content']}" for item in result["matches"]]
    if result["truncated"]:
        lines.append("結果已達上限，請縮小關鍵字或檔案範圍。")
    return "\n".join(lines) or "找不到符合的內容。"


def list_workspace_files() -> str:
    """
    【瀏覽工作區檔案列表】
    列出工作區 sandbox 中的所有檔案、大小及最後修改時間。
    """
    if not os.path.exists(get_workspace_dir()):
        return "工作區為空。"

    files_list = []
    for root, dirs, files in walk_workspace():
        for file in files:
            full_p = os.path.join(root, file)
            rel_p = os.path.relpath(full_p, get_workspace_dir())
            size = os.path.getsize(full_p)
            files_list.append(f"- {rel_p} ({size} bytes)")

    if not files_list:
        return "工作區目前尚無檔案。"
    return "【工作區檔案列表】:\n" + "\n".join(files_list)


def read_workspace_file(file_name: str, start_line: int = 1, end_line: int = -1) -> str:
    """
    【讀取工作區檔案】
    讀取工作區中指定檔案的內容。支援指定起始行 (start_line) 與結束行 (end_line) 進行局部精確閱讀。
    """
    try:
        full_path = _resolve_safe_path(file_name)
        if not os.path.exists(full_path):
            return ToolResult.failed(f"錯誤：檔案 '{file_name}' 不存在於工作區中。")

        from app.storage.document_import import read_workspace_text
        lines = read_workspace_text(full_path).splitlines(keepends=True)

        total_lines = len(lines)
        s = max(1, start_line)
        e = total_lines if end_line == -1 or end_line > total_lines else max(s, end_line)

        selected_lines = lines[s - 1:e]
        numbered_lines = [f"{i + s:4d} | {line}" for i, line in enumerate(selected_lines)]

        header = f"=== 檔案: {file_name} (顯示第 {s} 至 {e} 行 / 共 {total_lines} 行) ===\n"
        return header + "".join(numbered_lines)
    except Exception as e:
        log("workspace.exception", level=40, exc_info=True)
        return ToolResult.failed(f"讀取檔案失敗: {str(e)}")


def write_workspace_file(file_name: str, content: str) -> str:
    """
    【建立或覆寫工作區檔案】
    在工作區中建立新檔案或覆寫既有檔案。若為 .py 檔案，寫入後會自動執行 AST 語法檢測，確保語法正確。
    """
    try:
        full_path = _resolve_safe_path(file_name)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # 若是 python 檔案，先驗證語法
        if file_name.endswith(".py"):
            try:
                ast.parse(content, filename=file_name)
            except SyntaxError as e:
                log("workspace.syntax_failed", level=40, exc_info=True)
                return ToolResult.failed(f"語法檢查未通過，取消寫入！錯誤 (第 {e.lineno} 行): {e.msg}\n請修正後再次嘗試。")

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        line_count = len(content.splitlines())
        return f"成功寫入檔案 '{file_name}' (共 {line_count} 行)！已通過安全與語法驗證。"
    except Exception as e:
        log("workspace.exception", level=40, exc_info=True)
        return ToolResult.failed(f"寫入檔案失敗: {str(e)}")


def edit_code_chunk(file_name: str, target_code: str, replacement_code: str) -> str:
    """
    【Claude Code 風格精準區塊替換】
    安全替換檔案中特定的一小段代碼區塊。
    target_code 必須在檔案中有唯一匹配項。替換後會自動驗證語法並產出 Diff 對比報告。
    """
    try:
        full_path = _resolve_safe_path(file_name)
        if not os.path.exists(full_path):
            return ToolResult.failed(f"錯誤：目標檔案 '{file_name}' 不存在。")

        with open(full_path, "r", encoding="utf-8") as f:
            original_content = f.read()

        # 檢查 target_code 是否存在且唯一
        count = original_content.count(target_code)
        if count == 0:
            return ToolResult.failed(f"替換失敗：在 '{file_name}' 中找不到完全相符的 target_code。請先使用 read_workspace_file 查閱準確代碼與縮排。")
        elif count > 1:
            return ToolResult.failed(f"替換失敗：在 '{file_name}' 中找到 {count} 處匹配項，存在歧義。請擴大 target_code 的上下文範圍使其具備唯一性。")

        # 執行替換
        new_content = original_content.replace(target_code, replacement_code, 1)

        # 若是 Python 檔案，做 AST 語法檢查
        if file_name.endswith(".py"):
            try:
                ast.parse(new_content, filename=file_name)
            except SyntaxError as e:
                log("workspace.syntax_failed", level=40, exc_info=True)
                return ToolResult.failed(f"替換失敗 (語法校驗未通過)：修改後在第 {e.lineno} 行出現語法錯誤 ({e.msg})！已自動放棄修改以保證代碼完整。")

        # 寫回檔案
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # 產出 Diff
        diff_lines = list(difflib.unified_diff(
            original_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{file_name}",
            tofile=f"b/{file_name}",
            n=2
        ))
        diff_str = "".join(diff_lines)

        return (
            f"成功修改 '{file_name}'！語法校驗合格。\n"
            f"【代碼變更對照 (Diff)】:\n```diff\n{diff_str}\n```"
        )
    except Exception as e:
        log("workspace.exception", level=40, exc_info=True)
        return ToolResult.failed(f"修訂代碼失敗: {str(e)}")


def run_python(script_name: str, arguments: str = "", background: bool = False, wait_seconds: int = 30) -> str:
    """執行工作區 Python 腳本；background=True 立即回傳工作 ID。
    前景最多等待 wait_seconds（1～60 秒），尚未結束會保留背景工作，不強制終止。
    用 get_job 查詢結果、stop_job 停止。使用者未要求時，不主動執行測試。
    """
    import shlex
    from app.storage.jobs import job_manager, get_job
    from app.tools.history_memory import memory_session
    full_path = _resolve_safe_path(script_name)
    if not os.path.isfile(full_path):
        raise FileNotFoundError(f"找不到工作區腳本：{script_name}")
    if not 1 <= wait_seconds <= 60:
        raise ValueError("wait_seconds 必須為 1～60 秒。")
    args = shlex.split(arguments, posix=os.name != "nt")
    if os.name == "nt":
        args = [arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "\"'" else arg for arg in args]
    job_id = job_manager.start(memory_session.get(), [sys.executable, full_path, *args], get_workspace_dir())
    if not background:
        job_manager.wait(job_id, wait_seconds)
    return get_job(job_id)
