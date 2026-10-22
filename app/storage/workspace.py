"""專案共用工作區；未分類對話各自隔離檔案與規則。"""
import os
import re
import hashlib
from contextvars import ContextVar
from pathlib import Path
from app.config import WORKSPACE_DIR

workspace_scope = ContextVar("workspace_scope", default=None)


def project_workspace(project_id=None):
    root = Path(WORKSPACE_DIR).resolve()
    if project_id:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", project_id):
            raise ValueError("專案 ID 無效，無法建立工作區。")
        folder = (root / "projects" / project_id).resolve()
        if not folder.is_relative_to(root):
            raise ValueError("專案工作區超出根目錄。")
    else:
        folder = root  # 舊共用資料保留；實際對話由 session_workspace 選定子目錄。
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def session_workspace(session):
    if session.get("project_id"):
        return project_workspace(session["project_id"])
    session_id = session["id"]
    name = session_id if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", session_id) else hashlib.sha256(session_id.encode()).hexdigest()
    folder = Path(project_workspace()) / "conversations" / name
    folder = folder.resolve()
    if not folder.is_relative_to(Path(WORKSPACE_DIR).resolve() / "conversations"):
        raise ValueError("對話工作區超出根目錄。")
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def get_workspace_dir():
    return workspace_scope.get() or project_workspace()


def resolve_path(file_name):
    root = Path(get_workspace_dir()).resolve()
    path = (root / file_name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("檔案路徑超出目前工作區。")
    if root == Path(WORKSPACE_DIR).resolve() and any(path.is_relative_to(root / name) for name in ("projects", "conversations")):
        raise ValueError("不能直接讀寫其他專案或對話的工作區。")
    return str(path)


def walk_workspace(root=None):
    root = Path(root or get_workspace_dir()).resolve()
    base = Path(WORKSPACE_DIR).resolve()
    def allowed(path):
        path = path.resolve()
        return path.is_relative_to(root) and not (root == base and any(path.is_relative_to(base / name) for name in ("projects", "conversations")))
    for folder, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}
                   and allowed(Path(folder) / name)]
        files = [name for name in files if allowed(Path(folder) / name)]
        yield folder, dirs, files
