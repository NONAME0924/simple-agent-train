"""工作區檔案、搜尋、地圖、SDD 任務與文件文字匯入 API。"""
import asyncio
import datetime
import os
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from app.logging_setup import log
from app.storage.document_import import import_document, read_workspace_text, MAX_UPLOAD, SUPPORTED
from app.storage.jobs import job_manager
from app.storage.memory import memory_manager
from app.storage.plan_tasks import TaskStatus, task_list, change_task
from app.storage.workspace import get_workspace_dir, walk_workspace
from app.tools.workspace_tools import (
    parse_py_ast, get_workspace_code_map, search_workspace,
    build_workspace_directed_graph, _resolve_safe_path,
)

router = APIRouter()


class TaskEdit(BaseModel):
    task_line: int = Field(ge=1)
    status: TaskStatus
    revision: str


@router.get("/api/workspace/files")
def get_workspace_files():
    """
    取得工作區目錄樹與 Python AST 語意結構。
    供前端即時視覺化展示工作區檔案、類別、函式簽名與行號。
    """
    if not os.path.exists(get_workspace_dir()):
        return {"files": [], "workspace_dir": get_workspace_dir()}

    file_tree = []
    for root, dirs, files in walk_workspace():
        for file in sorted(files):
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, get_workspace_dir())
            stat = os.stat(full_path)

            file_info = {
                "name": file,
                "path": rel_path,
                "size": stat.st_size,
                "updated_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "is_py": file.endswith(".py"),
                "ast": None
            }

            if file.endswith(".py"):
                file_info["ast"] = parse_py_ast(full_path)

            file_tree.append(file_info)

    return {
        "files": file_tree,
        "workspace_dir": os.path.abspath(get_workspace_dir())
    }


@router.get("/api/workspace/file")
def get_workspace_file_content(path: str):
    """取得工作區中特定檔案的完整內容，供前端代碼檢視器預覽"""
    try:
        full_path = _resolve_safe_path(path)
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="檔案不存在")
        content = read_workspace_text(full_path)
        return {
            "path": path,
            "content": content,
            "lines": len(content.splitlines())
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        log("workspace.preview_failed", level=40, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/workspace/download")
def download_workspace_file(path: str):
    try:
        full_path = _resolve_safe_path(path)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="檔案不存在。")
    return FileResponse(full_path, filename=os.path.basename(full_path))


@router.get("/api/workspace/map")
def get_workspace_map_text():
    """取得文字版全專案代碼架構地圖 (Aider 風格)"""
    return {"map": get_workspace_code_map(include_graph=False)}


@router.get("/api/workspace/graph")
def get_workspace_graph():
    """取得工作區全庫 Mermaid 節點有向圖 (Directed Graph)"""
    nodes = {}
    return {"mermaid": build_workspace_directed_graph(node_targets=nodes), "nodes": nodes}


@router.get("/api/workspace/search")
def search_workspace_content(q: str = Query(min_length=1, max_length=200), pattern: str = "*", limit: int = Query(default=50, ge=1, le=100)):
    return search_workspace(q, pattern, limit)


@router.get("/api/workspace/tasks")
def list_tasks():
    return task_list()


@router.patch("/api/workspace/tasks")
def edit_task(data: TaskEdit, request: Request, session_id: str):
    current = memory_manager.get_session(session_id)
    if not current:
        raise HTTPException(status_code=404, detail="找不到目前對話。")
    for session in memory_manager.list_sessions():
        same_workspace = session["project_id"] == current["project_id"] if current["project_id"] else session["id"] == current["id"]
        if same_workspace and (
            session["id"] in request.app.state.agent.runs or job_manager.has_active(session["id"])):
            raise HTTPException(status_code=409, detail="此工作區仍有執行中的工作；請完成後再手動改任務狀態。")
    try:
        return change_task(data.task_line, data.status, data.revision)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.get("/api/workspace/import-formats")
def import_formats():
    return {"formats": SUPPORTED, "max_bytes": MAX_UPLOAD, "images": False, "uses_model": False, "ocr": False}


@router.post("/api/workspace/import")
async def upload_document(request: Request):
    name = unquote(request.headers.get("X-File-Name", "document.txt"))
    if request.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(status_code=415, detail="不匯入圖片；僅擷取文件中的文字。")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(status_code=413, detail="單一文件最多 25 MiB。")
    try:
        return await asyncio.to_thread(import_document, bytes(data), name)
    except ValueError as error:
        log("document.rejected", level=30, exc_info=True, name=name, error=str(error))
        raise HTTPException(status_code=422, detail=str(error))
    except Exception:
        log("document.failed", level=40, exc_info=True, name=name)
        raise HTTPException(status_code=422, detail="文件文字擷取失敗，完整錯誤已記入 log。")
